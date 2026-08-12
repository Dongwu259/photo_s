#!/bin/bash
# PhotoS — 一键安装脚本 One-Click Setup Script
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh              # 安装到当前环境 Install to current Python
#   ./setup.sh --app        # 创建 .app 捆绑包 Create macOS .app bundle
#
# Requirements: Python 3.9+, pip3

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "📷 PhotoS — 批量图片压缩与格式转换工具"
echo "========================================"
echo ""

# Check Python version
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || echo "(0,0)")
        if [[ "$ver" > "(3,8)" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "❌ 未找到 Python 3.9+。请先安装 Python 3.9 或更高版本。"
    echo "   Python 3.9+ is required. Install it from https://www.python.org/downloads/"
    exit 1
fi

echo "✅ 找到 Python: $PYTHON ($($PYTHON --version))"

# Install dependencies
echo ""
echo "📦 安装依赖 Installing dependencies..."
"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install -r requirements.txt -q

echo "✅ 依赖安装完成 Dependencies installed."
echo ""

# Create convenience symlink (optional)
if [[ "$1" == "--link" ]]; then
    LINK_PATH="/usr/local/bin/photo-s"
    echo "🔗 创建快捷方式 Creating symlink at $LINK_PATH..."
    sudo mkdir -p /usr/local/bin 2>/dev/null || true
    echo '#!/bin/bash' | sudo tee "$LINK_PATH" > /dev/null
    echo "exec $PYTHON $SCRIPT_DIR/main.py \"\$@\"" | sudo tee -a "$LINK_PATH" > /dev/null
    sudo chmod +x "$LINK_PATH"
    echo "✅ 现在可以直接使用 'photo-s' 命令! You can now use the 'photo-s' command!"
fi

# Create macOS .app bundle
if [[ "$1" == "--app" ]]; then
    echo ""
    echo "🍎 创建 macOS .app 捆绑包 Creating macOS .app bundle..."

    APP_DIR="$SCRIPT_DIR/PhotoS.app"
    mkdir -p "$APP_DIR/Contents/MacOS"
    mkdir -p "$APP_DIR/Contents/Resources"

    # Create launcher script
    cat > "$APP_DIR/Contents/MacOS/PhotoS" << 'LAUNCHER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"
cd "$SCRIPT_DIR"
exec python3 "$SCRIPT_DIR/main.py" gui
LAUNCHER
    chmod +x "$APP_DIR/Contents/MacOS/PhotoS"

    # Create Info.plist
    cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>PhotoS</string>
    <key>CFBundleDisplayName</key>
    <string>PhotoS — 图片批量压缩</string>
    <key>CFBundleIdentifier</key>
    <string>com.photos.app</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>PhotoS</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

    echo "✅ .app 捆绑包创建完成! App bundle created at: $APP_DIR"
    echo "   你可以将其拖到 Applications 文件夹。"
    echo "   You can drag it to your Applications folder."
fi

echo ""
echo "════════════════════════════════════════════"
echo "🎉 PhotoS 安装完成! Installation complete!"
echo ""
echo "使用方法 Usage:"
echo "  GUI 模式:  $PYTHON $SCRIPT_DIR/main.py"
echo "  CLI 模式:  $PYTHON $SCRIPT_DIR/main.py --help"
if [[ "$1" == "--link" ]]; then
    echo "  快捷命令:  photo-s"
fi
echo ""
echo "📖 详细文档 Full docs: $SCRIPT_DIR/README.md"
echo "════════════════════════════════════════════"
