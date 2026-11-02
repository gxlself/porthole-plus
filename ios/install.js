(function () {
  var ua = navigator.userAgent;
  // iPadOS 13+ reports itself as a Mac; touch points tell them apart.
  var isIOS = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  var inApp = /MicroMessenger|QQ\/|Weibo|DingTalk|Lark|Feishu|AlipayClient/i.test(ua);
  var manifest = new URL('manifest.plist', location.href).href;

  function show(id) {
    ['state-ok', 'state-inapp', 'state-desktop'].forEach(function (s) {
      document.getElementById(s).hidden = s !== id;
    });
  }

  document.getElementById('install').href =
    'itms-services://?action=download-manifest&url=' + encodeURIComponent(manifest);

  if (!isIOS) {
    show('state-desktop');
    if (window.qrcode) {
      var qr = qrcode(0, 'M');
      qr.addData(location.href.split('#')[0]);
      qr.make();
      document.getElementById('qr').innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
    }
  } else if (inApp) {
    show('state-inapp');
  } else {
    show('state-ok');
  }

  document.getElementById('copy').addEventListener('click', function (e) {
    var url = location.href.split('#')[0];
    var done = function () { e.target.textContent = '已复制，去 Safari 粘贴打开'; };
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt('复制这个链接', url); });
    else prompt('复制这个链接', url);
  });

  fetch('version.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (v) {
    if (!v) return;
    document.getElementById('v-version').textContent = v.version + ' (' + v.build + ')';
    document.getElementById('v-size').textContent = (v.bytes / 1048576).toFixed(1) + ' MB';
    document.getElementById('v-date').textContent = v.date;
  }).catch(function () {});
})();
