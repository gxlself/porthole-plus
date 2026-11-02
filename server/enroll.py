#!/usr/bin/env python3
"""舷窗Plus iPhone 自动登记安装服务（Linux 服务器，rcodesign 重签）。

流程：
  1. 手机 Safari 打开 /enroll.mobileconfig，装一个「描述文件服务」。
  2. 系统把带签名的设备信息（UDID 等）POST 到 /udid，本服务验证是苹果设备签的，记下 UDID，301 跳到 /wait?t=…。
  3. 后台线程攒一小批新设备：App Store Connect API 登记设备 → 重建 Ad Hoc 描述文件 → 用 codesign 重签 IPA。
  4. /wait 页面轮询 /status，这台设备进了新描述文件就显示安装按钮（itms-services → /manifest.plist → /app.ipa）。

环境变量：ASC_KEY_ID ASC_ISSUER_ID ASC_KEY_PATH（个人团队 API Key）、SRC_IPA（未签名或任意签名的原始包）、
SECRETS_DIR（发布证书私钥所在目录，私钥在服务器上生成、不离开服务器）、RCODESIGN、DATA_DIR、PORT（默认 8795）、
MAX_PER_CLASS（默认 95）、SITE（静态页面前缀，默认同域）。只监听 127.0.0.1，由 nginx 对外提供 HTTPS。
"""
import base64, hashlib, hmac, html, io, zipfile, json, os, plistlib, re, secrets, shutil, subprocess, sys, tempfile, threading, time, uuid
import urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import jwt  # pyjwt[crypto]

BUNDLE_ID = os.environ.get("BUNDLE_ID", "com.gxlself.offlinearena")
APP_TITLE = "舷窗Plus"
PROFILE_NAME = "PortholePlus AdHoc"
DATA = os.path.abspath(os.environ.get("DATA_DIR", os.path.expanduser("~/swarm-arena/porthole-enroll")))
PORT = int(os.environ.get("PORT", "8795"))
MAX_PER_CLASS = int(os.environ.get("MAX_PER_CLASS", "95"))
SITE = os.environ.get("SITE", "")
SECRETS = os.environ.get("SECRETS_DIR", "/opt/porthole/secrets")
RCODESIGN = os.environ.get("RCODESIGN", "/opt/porthole/bin/rcodesign")
os.makedirs(DATA, exist_ok=True)
STATE_FILE = os.path.join(DATA, "state.json")
SECRET_FILE = os.path.join(DATA, "secret")
if not os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "w") as f:
        f.write(secrets.token_hex(32))
    os.chmod(SECRET_FILE, 0o600)
SECRET = open(SECRET_FILE).read().strip().encode()

lock = threading.Lock()
wake = threading.Event()


def log(*a):
    print(time.strftime("%m-%d %H:%M:%S"), *a, flush=True)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"devices": {}, "rev": 0, "error": ""}


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


state = load_state()


def token_for(udid):
    return hmac.new(SECRET, udid.encode(), hashlib.sha256).hexdigest()[:24]


# ---------- App Store Connect API ----------
def asc(method, path, body=None):
    key = open(os.path.expanduser(os.environ["ASC_KEY_PATH"])).read()
    now = int(time.time())
    tok = jwt.encode({"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"},
                     key, algorithm="ES256", headers={"kid": os.environ["ASC_KEY_ID"]})
    req = urllib.request.Request("https://api.appstoreconnect.apple.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw.decode(errors="replace")[:500]}


def asc_all(path):
    out = []
    while path:
        code, d = asc("GET", path)
        if code != 200:
            raise RuntimeError(f"GET {path} → {code} {d}")
        out += d.get("data", [])
        nxt = d.get("links", {}).get("next")
        path = nxt.replace("https://api.appstoreconnect.apple.com", "") if nxt else None
    return out


def ensure_bundle_id():
    code, d = asc("GET", f"/v1/bundleIds?filter[identifier]={BUNDLE_ID}&limit=5")
    for b in d.get("data", []):
        if b["attributes"]["identifier"] == BUNDLE_ID:
            return b["id"]
    code, d = asc("POST", "/v1/bundleIds", {"data": {"type": "bundleIds", "attributes": {
        "identifier": BUNDLE_ID, "name": "PortholePlus", "platform": "IOS"}}})
    if code != 201:
        raise RuntimeError(f"登记 Bundle ID 失败：{code} {d}")
    return d["data"]["id"]


def distribution_cert_id():
    """服务器自己的 Apple Distribution 证书：没有就在这里生成私钥和 CSR，向苹果申请一张。"""
    key, pem, meta = (os.path.join(SECRETS, x) for x in ("dist.key", "dist.pem", "dist.json"))
    if os.path.exists(meta) and os.path.exists(pem):
        return json.load(open(meta))["id"]
    if not os.path.exists(key):
        run("openssl", "genrsa", "-out", key, "2048")
        os.chmod(key, 0o600)
    csr = run("openssl", "req", "-new", "-key", key, "-subj", "/CN=PortholePlus Enroll/emailAddress=noreply@gxlself.com")
    code, d = asc("POST", "/v1/certificates", {"data": {"type": "certificates", "attributes": {
        "certificateType": "DISTRIBUTION", "csrContent": csr}}})
    if code != 201:
        raise RuntimeError(f"申请发布证书失败：{code} {json.dumps(d)[:300]}")
    der = base64.b64decode(d["data"]["attributes"]["certificateContent"])
    pem_text = "-----BEGIN CERTIFICATE-----\n" + "\n".join(
        base64.b64encode(der).decode()[i:i + 64] for i in range(0, len(base64.b64encode(der)), 64)) + "\n-----END CERTIFICATE-----\n"
    with open(pem, "w") as f:
        f.write(pem_text)
    with open(meta, "w") as f:
        json.dump({"id": d["data"]["id"], "expires": d["data"]["attributes"].get("expirationDate")}, f)
    log("已申请发布证书", d["data"]["id"])
    return d["data"]["id"]


def register_devices(pending):
    devices = asc_all("/v1/devices?limit=200&filter[status]=ENABLED&fields[devices]=udid,deviceClass,platform")
    known = {d["attributes"]["udid"].upper(): d for d in devices}
    per_class = {}
    for d in devices:
        per_class[d["attributes"]["deviceClass"]] = per_class.get(d["attributes"]["deviceClass"], 0) + 1
    failed = {}
    for udid, info in pending.items():
        if udid.upper() in known:
            continue
        cls = "IPAD" if info.get("product", "").startswith("iPad") else "IPHONE"
        if per_class.get(cls, 0) >= MAX_PER_CLASS:
            failed[udid] = "这个开发者账号今年能登记的设备已经用完了"
            continue
        name = f"舷窗Plus {info.get('product', '')} {udid[-6:]}"[:50]
        code, d = asc("POST", "/v1/devices", {"data": {"type": "devices", "attributes": {
            "name": name, "udid": udid, "platform": "IOS"}}})
        if code == 201:
            per_class[cls] = per_class.get(cls, 0) + 1
            log("登记设备", name)
        elif code == 409:
            log("设备已存在或被拒", udid[-6:], json.dumps(d)[:200])
        else:
            failed[udid] = f"登记设备失败（{code}）"
            log("登记失败", udid[-6:], code, json.dumps(d)[:300])
    return failed


def rebuild_profile(bundle_rid, cert_rid):
    for p in asc_all(f"/v1/profiles?filter[name]={urllib.request.quote(PROFILE_NAME)}&limit=50"):
        asc("DELETE", f"/v1/profiles/{p['id']}")
    devices = [d for d in asc_all("/v1/devices?limit=200&filter[status]=ENABLED&fields[devices]=udid,deviceClass,platform")
               if d["attributes"]["deviceClass"] in ("IPHONE", "IPAD", "IPOD") and d["attributes"]["platform"] == "IOS"]
    code, d = asc("POST", "/v1/profiles", {"data": {"type": "profiles", "attributes": {
        "name": PROFILE_NAME, "profileType": "IOS_APP_ADHOC"}, "relationships": {
        "bundleId": {"data": {"type": "bundleIds", "id": bundle_rid}},
        "certificates": {"data": [{"type": "certificates", "id": cert_rid}]},
        "devices": {"data": [{"type": "devices", "id": x["id"]} for x in devices]}}}})
    if code != 201:
        raise RuntimeError(f"生成 Ad Hoc 描述文件失败：{code} {json.dumps(d)[:300]}")
    content = base64.b64decode(d["data"]["attributes"]["profileContent"])
    udids = {x["attributes"]["udid"].upper() for x in devices}
    return content, udids


# ---------- 阿里云 OSS（大文件走 CDN，服务器带宽太小） ----------
def oss_put(path, key, ctype="application/octet-stream"):
    import email.utils
    bucket, endpoint = os.environ["OSS_BUCKET"], os.environ["OSS_ENDPOINT"]
    date = email.utils.formatdate(usegmt=True)
    sts = f"PUT\n\n{ctype}\n{date}\n/{bucket}/{key}"
    sig = base64.b64encode(hmac.new(os.environ["OSS_ACCESS_KEY_SECRET"].encode(), sts.encode(), hashlib.sha1).digest()).decode()
    with open(path, "rb") as f:
        req = urllib.request.Request(f"https://{bucket}.{endpoint}/{key}", data=f.read(), method="PUT", headers={
            "Date": date, "Content-Type": ctype, "Authorization": f"OSS {os.environ['OSS_ACCESS_KEY_ID']}:{sig}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        if r.status != 200:
            raise RuntimeError(f"上传 OSS 失败：{r.status}")
    return os.environ["OSS_PUBLIC_BASE_URL"].rstrip("/") + "/" + key


def oss_req(method, key, sub="", data=None, ctype="", headers=None):
    import email.utils
    bucket, endpoint = os.environ["OSS_BUCKET"], os.environ["OSS_ENDPOINT"]
    date = email.utils.formatdate(usegmt=True)
    headers = dict(headers or {})
    oss_h = "".join(f"{k.lower()}:{v}\n" for k, v in sorted(headers.items()) if k.lower().startswith("x-oss-"))
    sts = f"{method}\n\n{ctype}\n{date}\n{oss_h}/{bucket}/{key}{('?' + sub) if sub else ''}"
    sig = base64.b64encode(hmac.new(os.environ["OSS_ACCESS_KEY_SECRET"].encode(), sts.encode(), hashlib.sha1).digest()).decode()
    headers.update({"Date": date, "Authorization": f"OSS {os.environ['OSS_ACCESS_KEY_ID']}:{sig}"})
    if ctype:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(f"https://{bucket}.{endpoint}/{key}{('?' + sub) if sub else ''}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.headers, r.read()


def oss_compose(base_key, tail, key):
    """新对象 = OSS 上已有的静态前缀（服务端拷贝）+ 这次重签的小尾巴。只上传尾巴。"""
    _, body = oss_req("POST", key, "uploads")
    upload_id = re.search(rb"<UploadId>([^<]+)</UploadId>", body).group(1).decode()
    _, body = oss_req("PUT", key, f"partNumber=1&uploadId={upload_id}",
                      headers={"x-oss-copy-source": f"/{os.environ['OSS_BUCKET']}/{base_key}"})
    etag1 = re.search(rb"<ETag>([^<]+)</ETag>", body).group(1).decode().replace("&quot;", '"')
    h, _ = oss_req("PUT", key, f"partNumber=2&uploadId={upload_id}", data=tail, ctype="application/octet-stream")
    etag2 = h["ETag"]
    xml = (f"<CompleteMultipartUpload><Part><PartNumber>1</PartNumber><ETag>{etag1}</ETag></Part>"
           f"<Part><PartNumber>2</PartNumber><ETag>{etag2}</ETag></Part></CompleteMultipartUpload>").encode()
    oss_req("POST", key, f"uploadId={upload_id}", data=xml, ctype="application/xml")
    return os.environ["OSS_PUBLIC_BASE_URL"].rstrip("/") + "/" + key


# ---------- 重签 ----------
def run(*cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} 失败：{(r.stderr or r.stdout)[-400:]}")
    return r.stdout


ZIP_TIME = (2020, 1, 1, 0, 0, 0)
DYNAMIC = ("_CodeSignature/", "embedded.mobileprovision")  # 加上主程序：每次重签都会变的文件


def sign_files(cmd_tail):
    run(RCODESIGN, "sign", "--pem-file", os.path.join(SECRETS, "dist.key"), "--pem-file", os.path.join(SECRETS, "dist.pem"), *cmd_tail)


def app_files(app):
    out = []
    for root, dirs, files in os.walk(app):
        dirs.sort()
        for f in sorted(files):
            full = os.path.join(root, f)
            out.append(os.path.relpath(full, app))
    return out


def write_entries(zf, app, rels):
    name = os.path.basename(app)
    for rel in rels:
        full = os.path.join(app, rel)
        zi = zipfile.ZipInfo(f"Payload/{name}/{rel}", ZIP_TIME)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (os.stat(full).st_mode & 0xFFFF) << 16
        with open(full, "rb") as f:
            zf.writestr(zi, f.read(), compresslevel=6)


def split_files(app):
    exe = plistlib.load(open(os.path.join(app, "Info.plist"), "rb"))["CFBundleExecutable"]
    static, dynamic = [], []
    for rel in app_files(app):
        (dynamic if rel == exe or rel.startswith(DYNAMIC) else static).append(rel)
    return static, dynamic


def prepare_base():
    """原始包换了：解开、把 Frameworks 签一次，静态部分打成 zip 前缀传到 OSS。之后每台新设备只需重签主程序。"""
    base = os.path.join(DATA, "base")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    run("unzip", "-q", os.environ["SRC_IPA"], "-d", base)
    app = os.path.join(base, "Payload", [x for x in os.listdir(os.path.join(base, "Payload")) if x.endswith(".app")][0])
    for sub in ("Frameworks", "PlugIns"):
        d = os.path.join(app, sub)
        if os.path.isdir(d):
            for x in sorted(os.listdir(d)):
                if x.endswith((".framework", ".dylib", ".appex")):
                    sign_files([os.path.join(d, x)])
    shutil.rmtree(os.path.join(app, "_CodeSignature"), ignore_errors=True)
    static, _ = split_files(app)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        write_entries(zf, app, static)
        prefix_len = zf.fp.tell()
    prefix = buf.getvalue()[:prefix_len]
    meta = {"app": app, "len": prefix_len, "sha": hashlib.sha256(prefix).hexdigest(), "key": ""}
    if os.environ.get("OSS_BUCKET"):
        meta["key"] = f"porthole/ios/base-{meta['sha'][:16]}.bin"
        tmp = os.path.join(DATA, "base.bin")
        with open(tmp, "wb") as f:
            f.write(prefix)
        oss_put(tmp, meta["key"])
        os.remove(tmp)
    log(f"静态部分 {prefix_len / 1048576:.1f} MB 已就绪", meta["key"])
    return meta


def resign(profile_bytes, out_ipa, base):
    work = tempfile.mkdtemp(prefix="pp-resign-", dir=DATA)
    try:
        app = os.path.join(work, os.path.basename(base["app"]))
        shutil.copytree(base["app"], app, symlinks=True)
        prof_path = os.path.join(work, "p.mobileprovision")
        with open(prof_path, "wb") as f:
            f.write(profile_bytes)
        shutil.copy(prof_path, os.path.join(app, "embedded.mobileprovision"))
        decoded = plistlib.loads(subprocess.run(["openssl", "smime", "-verify", "-inform", "DER", "-noverify", "-in", prof_path],
                                                capture_output=True).stdout)
        ent_path = os.path.join(work, "ent.plist")
        with open(ent_path, "wb") as f:
            plistlib.dump(decoded["Entitlements"], f)
        # Frameworks 已在 prepare_base 签好：这里只签主程序（--shallow 不碰嵌套包）
        sign_files(["--shallow", "-e", ent_path, app])
        static, dynamic = split_files(app)
        tmp_ipa = out_ipa + ".tmp"
        with zipfile.ZipFile(tmp_ipa, "w") as zf:
            write_entries(zf, app, static)
            write_entries(zf, app, dynamic)
        with open(tmp_ipa, "rb") as f:
            if hashlib.sha256(f.read(base["len"])).hexdigest() != base["sha"]:
                raise RuntimeError("静态部分和已上传的前缀对不上")
        os.replace(tmp_ipa, out_ipa)
        info = plistlib.load(open(os.path.join(app, "Info.plist"), "rb"))
        return info.get("CFBundleShortVersionString", "0"), decoded.get("ExpirationDate")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def src_stamp():
    try:
        st = os.stat(os.environ["SRC_IPA"])
    except FileNotFoundError:
        return ""
    return f"{st.st_size}-{int(st.st_mtime)}"


def worker():
    bundle_rid = cert_rid = None
    base = state.get("base")  # 重启后沿用已上传的静态前缀
    while True:
        wake.wait(30)
        wake.clear()
        time.sleep(8)  # 一个房间的人常常一起扫：攒一小批再重签
        with lock:
            pending = {u: d for u, d in state["devices"].items() if d["state"] == "pending"}
        if not src_stamp():
            continue  # 还没上传原始包
        need_build = not os.path.exists(os.path.join(DATA, "app.ipa")) or state.get("src") != src_stamp()
        if not pending and not need_build:
            continue
        try:
            bundle_rid = bundle_rid or ensure_bundle_id()
            cert_rid = cert_rid or distribution_cert_id()
            failed = register_devices(pending)
            profile, udids = rebuild_profile(bundle_rid, cert_rid)
            if not base or base.get("src") != src_stamp() or not os.path.isdir(base["app"]):
                base = prepare_base()
                base["src"] = src_stamp()
                with lock:
                    state["base"] = base
                    save_state(state)
            ipa = os.path.join(DATA, "app.ipa")
            version, expires = resign(profile, ipa, base)
            rev = state["rev"] + 1
            ipa_url = ""
            if base["key"]:
                with open(ipa, "rb") as f:
                    f.seek(base["len"])
                    tail = f.read()
                ipa_url = oss_compose(base["key"], tail, f"porthole/ios/PortholePlus-{version}-r{rev}-{secrets.token_hex(4)}.ipa")
            with lock:
                state["ipa_url"] = ipa_url
                state["rev"] += 1
                state["src"] = src_stamp()
                state["version"] = version
                state["expires"] = expires.strftime("%Y-%m-%d") if expires else ""
                for u in pending:
                    d = state["devices"][u]
                    if u in failed:
                        d.update(state="error", msg=failed[u])
                    elif u.upper() in udids:
                        d.update(state="ready", msg="")
                    else:
                        d.update(state="error", msg="苹果没有把这台设备放进描述文件，稍后再试")
                state["error"] = ""
                save_state(state)
            log(f"重签完成 rev={state['rev']}，描述文件 {len(udids)} 台设备")
        except Exception as e:  # 下一轮重试；页面显示「还在处理」
            log("处理失败：", e)
            with lock:
                state["error"] = str(e)[:300]
                save_state(state)
            wake.set()
            time.sleep(60)


# ---------- HTTP ----------
def mobileconfig(base):
    return plistlib.dumps({
        "PayloadContent": {"URL": base + "/udid", "DeviceAttributes": ["UDID", "PRODUCT", "VERSION", "DEVICE_NAME"],
                           "Challenge": secrets.token_hex(8)},
        "PayloadOrganization": APP_TITLE, "PayloadDisplayName": f"{APP_TITLE} 安装登记",
        "PayloadDescription": "只读取这台设备的 UDID 和机型，用来登记安装。读取后会自动跳回安装页，这个描述文件不会留在设备上。",
        "PayloadIdentifier": "com.gxlself.portholeplus.enroll", "PayloadUUID": str(uuid.uuid4()).upper(),
        "PayloadType": "Profile Service", "PayloadVersion": 1})


def parse_device_reply(body):
    """验证 PKCS#7 是苹果设备证书签的，返回里面的 plist。"""
    with tempfile.NamedTemporaryFile(dir=DATA, suffix=".p7s") as f:
        f.write(body)
        f.flush()
        content = subprocess.run(["openssl", "smime", "-verify", "-inform", "DER", "-noverify", "-in", f.name],
                                 capture_output=True).stdout
        certs = subprocess.run(["openssl", "pkcs7", "-inform", "DER", "-print_certs", "-noout", "-in", f.name],
                               capture_output=True, text=True).stdout
    if "Apple iPhone Device CA" not in certs and "Apple iPhone Certification Authority" not in certs:
        raise ValueError("不是苹果设备签名的数据")
    return plistlib.loads(content)


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>舷窗Plus · 安装</title>
<link rel="stylesheet" href="{site}/assets/site.css"><link rel="stylesheet" href="{site}/ios/install.css"></head>
<body class="install"><header class="nav"><a class="brand" href="{site}/"><img src="{site}/assets/logo.svg" alt="" width="36" height="36"><span>舷窗<b>Plus</b></span></a></header>
<main class="wrap"><section class="app-card">
<img class="app-icon" src="{site}/assets/icon-512.png" alt="" width="112" height="112"><h1>舷窗Plus</h1>
<p class="sub" id="who">{product}</p>
<div id="busy"><div class="spinner"></div><p class="hint" id="msg">正在为这台设备签名，大约半分钟…</p></div>
<div id="ok" hidden><a class="btn install-btn" href="itms-services://?action=download-manifest&amp;url={manifest}">安装舷窗Plus</a>
<p class="hint">点「安装」后回到桌面，图标转完就能玩。第一次建房时请允许「本地网络」。</p></div>
<div id="err" class="notice" hidden><b>没装上</b><p id="errmsg"></p><a class="btn btn-line" href="{site}/ios/">回安装页重试</a></div>
</section></main>
<style>.spinner{{width:44px;height:44px;margin:8px auto 4px;border-radius:50%;border:5px solid var(--line);border-top-color:var(--brand);animation:sp 1s linear infinite}}@keyframes sp{{to{{transform:rotate(1turn)}}}}</style>
<script>
var t={token!r};
function poll(){{fetch('status?t='+t,{{cache:'no-store'}}).then(function(r){{return r.json()}}).then(function(s){{
 if(s.state==='ready'){{busy.hidden=true;ok.hidden=false;return}}
 if(s.state==='error'||s.state==='unknown'){{busy.hidden=true;err.hidden=false;errmsg.textContent=s.msg||'找不到这台设备的登记记录。';return}}
 if(s.msg)msg.textContent=s.msg;setTimeout(poll,3000)}}).catch(function(){{setTimeout(poll,5000)}})}}
poll();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "PortholePlus"

    def base(self):
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", f"127.0.0.1:{PORT}")
        scheme = "http" if host.startswith(("127.0.0.1", "localhost")) else "https"
        return f"{scheme}://{host}"

    def send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        log(self.address_string() if False else "-", fmt % args)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/healthz":
            with lock:
                ipa = os.path.join(DATA, "app.ipa")
                size = os.path.getsize(ipa) if os.path.exists(ipa) else 0
                date = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(ipa))) if size else ""
                return self.send(200, json.dumps({"ok": True, "rev": state["rev"], "version": state.get("version"),
                                                  "size": size, "date": date, "ready": bool(size)}),
                                 "application/json")
        if u.path == "/enroll.mobileconfig":
            return self.send(200, mobileconfig(self.base()), "application/x-apple-aspen-config",
                             {"Content-Disposition": 'attachment; filename="PortholePlus.mobileconfig"'})
        if u.path in ("/wait", "/status"):
            t = q.get("t", "")
            with lock:
                dev = next(({"udid": k, **v} for k, v in state["devices"].items() if v["token"] == t), None)
                err = state["error"]
            if u.path == "/status":
                if not dev:
                    return self.send(200, json.dumps({"state": "unknown"}), "application/json")
                msg = dev.get("msg") or ("苹果那边有点慢，还在重试…" if err and dev["state"] == "pending" else "")
                return self.send(200, json.dumps({"state": dev["state"], "msg": msg}, ensure_ascii=False), "application/json")
            product = html.escape(dev.get("product", "") if dev else "")
            page = PAGE.format(site=SITE, token=t, product=product or "iPhone / iPad",
                               manifest=html.escape(self.base() + "/manifest.plist"))
            return self.send(200, page, "text/html; charset=utf-8")
        if u.path == "/manifest.plist":
            with lock:
                rev, version, ipa_url = state["rev"], state.get("version", "0"), state.get("ipa_url")
            b = self.base()
            return self.send(200, plistlib.dumps({"items": [{"assets": [
                {"kind": "software-package", "url": ipa_url or f"{b}/app.ipa?rev={rev}"},
                {"kind": "display-image", "url": f"{b}{SITE}/assets/icon-57.png"},
                {"kind": "full-size-image", "url": f"{b}{SITE}/assets/icon-512.png"}],
                "metadata": {"bundle-identifier": BUNDLE_ID, "bundle-version": version, "kind": "software",
                             "title": APP_TITLE}}]}), "application/xml")
        if u.path == "/app.ipa":
            path = os.path.join(DATA, "app.ipa")
            if not os.path.exists(path):
                return self.send(404, "还没有签好的安装包")
            size = os.path.getsize(path)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            if self.command != "HEAD":
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)
            return
        if u.path == "/":
            return self.send(302, "", extra={"Location": SITE + "/ios/"})
        self.send(404, "not found")

    def do_POST(self):
        if urlparse(self.path).path != "/udid":
            return self.send(404, "not found")
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > 64 * 1024:
            return self.send(400, "bad request")
        try:
            info = parse_device_reply(self.rfile.read(n))
            udid = str(info["UDID"]).strip()
            if not re.fullmatch(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}|[0-9a-fA-F]{40}", udid):
                raise ValueError("UDID 格式不对")
        except Exception as e:
            log("拒绝 /udid：", e)
            return self.send(400, "无法识别这台设备")
        t = token_for(udid)
        with lock:
            d = state["devices"].get(udid)
            if not d or d["state"] == "error":
                state["devices"][udid] = {"token": t, "state": "pending", "msg": "", "product": str(info.get("PRODUCT", "")),
                                          "version": str(info.get("VERSION", "")), "at": int(time.time())}
                save_state(state)
                wake.set()
                log("新设备", info.get("PRODUCT"), udid[-6:])
        # 苹果要求用 301 让 Safari 打开后续页面
        self.send(301, "", extra={"Location": self.base() + "/wait?t=" + t})


def main():
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_PATH", "SRC_IPA"):
        if not os.environ.get(k):
            sys.exit(f"缺少环境变量 {k}")
    threading.Thread(target=worker, daemon=True).start()
    wake.set()  # 启动时没有签好的包、或者原始包换了，就先签一版
    log(f"监听 127.0.0.1:{PORT}，数据目录 {DATA}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
