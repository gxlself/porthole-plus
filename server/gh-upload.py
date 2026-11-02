#!/usr/bin/env python3
"""阿里云上的 GitHub 上传中转（要兼容那台机器的 Python 3.6）（火山出口太慢，阿里云快 3–4 倍）。
只能经 ssh 强制命令调用，命令在 SSH_ORIGINAL_COMMAND：
  has <slug> <sha>                     这份不变部分在不在，打印 yes/no
  base <slug> <sha>                    stdin 是不变部分，存下来
  publish <slug> <repo> <tag> <asset> <sha>
                                       stdin 是变动部分；拼成完整 IPA 传到 GitHub Release，打印下载地址
令牌在 /opt/appupload/secrets/gh_token。
"""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request

ROOT = "/opt/appupload"
TOKEN = open(f"{ROOT}/secrets/gh_token").read().strip()
NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def gh(method, url, body=None, ctype="application/json"):
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            return r.status, json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        return e.code, None


def release(repo, tag):
    code, rel = gh("GET", f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
    if code == 200:
        return rel
    code, rel = gh("POST", f"https://api.github.com/repos/{repo}/releases", json.dumps({
        "tag_name": tag, "name": f"iPhone 内测安装包（{tag}）", "prerelease": True,
        "body": "服务器自动更新。只能在登记过的设备上安装，请从安装页进入，不要直接下载。"}).encode())
    if code != 201:
        sys.exit(f"建 release 失败 {code}")
    return rel


def main():
    args = os.environ.get("SSH_ORIGINAL_COMMAND", "").split()
    if not args or not all(NAME.match(a) or re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", a) for a in args[1:]):
        sys.exit("bad command")
    cache = f"{ROOT}/cache/{args[1]}"
    os.makedirs(cache, exist_ok=True)
    if args[0] == "has":
        print("yes" if os.path.exists(f"{cache}/base-{args[2]}.bin") else "no")
    elif args[0] == "base":
        tmp = f"{cache}/.incoming"
        with open(tmp, "wb") as f:
            shutil.copyfileobj(sys.stdin.buffer, f)
        if hashlib.sha256(open(tmp, "rb").read()).hexdigest() != args[2]:
            os.remove(tmp)
            sys.exit("不变部分校验失败")
        for old in os.listdir(cache):
            if old.startswith("base-"):
                os.remove(f"{cache}/{old}")
        os.replace(tmp, f"{cache}/base-{args[2]}.bin")
        print("ok")
    elif args[0] == "publish":
        _, slug, repo, tag, asset, sha = args
        base = f"{cache}/base-{sha}.bin"
        if not os.path.exists(base):
            sys.exit("没有这份不变部分")
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".ipa", delete=False) as f:
            with open(base, "rb") as b:
                shutil.copyfileobj(b, f)
            shutil.copyfileobj(sys.stdin.buffer, f)
            ipa = f.name
        try:
            rel = release(repo, tag)
            for a in rel.get("assets", []):
                if a["name"] == asset:
                    gh("DELETE", a["url"])
            up = rel["upload_url"].split("{")[0] + "?name=" + asset
            out = subprocess.run(["curl", "-sS", "--fail", "-X", "POST", "-H", f"Authorization: Bearer {TOKEN}",
                                  "-H", "Content-Type: application/octet-stream", "--data-binary", f"@{ipa}", up],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=1800)
            if out.returncode != 0:
                sys.exit("上传失败 " + out.stderr[:200])
            url = json.loads(out.stdout)["browser_download_url"]
            # 只留最近 3 个包
            code, rel = gh("GET", f"https://api.github.com/repos/{repo}/releases/tags/{tag}")
            olds = sorted((a for a in rel["assets"] if a["name"] != asset), key=lambda a: a["created_at"])
            for a in olds[:-2]:
                gh("DELETE", a["url"])
            print(url)
        finally:
            os.remove(ipa)
    else:
        sys.exit("bad command")


main()
