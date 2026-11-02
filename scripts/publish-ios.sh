#!/usr/bin/env bash
# 发布一版 iPhone 内测包：上传 IPA（和可选的 APK）到 GitHub Release，生成 ios/manifest.plist 和 ios/version.json，提交并推送。
# 用法：scripts/publish-ios.sh <ipa> <版本号> <构建号> [apk]
set -euo pipefail
ipa=$1; version=$2; build=$3; apk=${4:-}
repo=gxlself/porthole-plus
site=https://gxlself.github.io/porthole-plus
root=$(cd "$(dirname "$0")/.." && pwd)
tag="v$version-$build"
[[ -f "$ipa" ]] || { echo "找不到 $ipa" >&2; exit 1; }
bundle=$(unzip -p "$ipa" 'Payload/*.app/Info.plist' | plutil -extract CFBundleIdentifier raw -o - -)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cp "$ipa" "$tmp/PortholePlus-$version-$build.ipa"; files=("$tmp/PortholePlus-$version-$build.ipa")
if [[ -n "$apk" ]]; then cp "$apk" "$tmp/PortholePlus-$version-$build.apk"; files+=("$tmp/PortholePlus-$version-$build.apk"); fi
gh release create "$tag" "${files[@]}" -R "$repo" -t "舷窗Plus $version ($build)" -n "内测版 $version ($build)。iPhone 请打开 $site/ios/ 安装。" --latest
ipa_url="https://github.com/$repo/releases/download/$tag/PortholePlus-$version-$build.ipa"
cat > "$root/ios/manifest.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict><key>kind</key><string>software-package</string><key>url</key><string>$ipa_url</string></dict>
        <dict><key>kind</key><string>display-image</string><key>url</key><string>$site/assets/icon-57.png</string></dict>
        <dict><key>kind</key><string>full-size-image</string><key>url</key><string>$site/assets/icon-512.png</string></dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key><string>$bundle</string>
        <key>bundle-version</key><string>$version</string>
        <key>kind</key><string>software</string>
        <key>title</key><string>舷窗Plus</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>
PLIST
bytes=$(stat -f %z "$ipa")
printf '{"version":"%s","build":"%s","bytes":%s,"date":"%s","tag":"%s"}\n' "$version" "$build" "$bytes" "$(date +%Y-%m-%d)" "$tag" > "$root/ios/version.json"
git -C "$root" add ios/manifest.plist ios/version.json
git -C "$root" commit -q -m "iOS $version ($build)"
git -C "$root" push -q origin main
echo "已发布 $tag：$site/ios/"
