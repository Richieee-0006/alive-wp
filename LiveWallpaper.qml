import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import Quickshell.Io
import "."

ShellRoot {
    id: rootShell

    // Configuration
    property string wallpaperPath: Quickshell.env("LIVE_WALLPAPER_PATH")
    property string depthPath: Quickshell.env("LIVE_DEPTH_PATH")
    property string fgPath: Quickshell.env("LIVE_FG_PATH")
    property string bgPath: Quickshell.env("LIVE_BG_PATH")
    readonly property bool hasDiscreteLayers: fgPath !== "" && bgPath !== ""
    property bool showClock: Quickshell.env("LIVE_SHOW_CLOCK") === "1"
    property real clockDepth: 0.45
    property real maxDisplacement: 0.038

    // Ambient breathing drift (gentle continuous living motion)
    property real ambientTime: 0.0
    Timer {
        interval: 16
        running: true
        repeat: true
        onTriggered: rootShell.ambientTime += 0.016
    }
    readonly property real ambientOffsetX: Math.sin(ambientTime * 0.75) * 0.08
    readonly property real ambientOffsetY: Math.cos(ambientTime * 0.55) * 0.05

    // Normalized mouse offset relative to screen center: (-0.5 .. 0.5)
    property real currentOffsetX: 0.0
    property real currentOffsetY: 0.0

    Behavior on currentOffsetX {
        NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
    }
    Behavior on currentOffsetY {
        NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
    }

    Component.onCompleted: {
        if ((rootShell.depthPath === "" || !rootShell.hasDiscreteLayers) && rootShell.wallpaperPath !== "") {
            depthIndexReader.running = true
        }
    }

    // Direct lookup in layers index.json for depth, fg, and bg
    Process {
        id: depthIndexReader
        running: false
        command: [
            "python3", "-c",
            "import json, os, sys; p = os.path.expanduser('~/.cache/wallpaper_picker/layers/index.json'); d = json.load(open(p)) if os.path.exists(p) else {}; base = sys.argv[1]; full = sys.argv[2] if len(sys.argv) > 2 else ''; print((d.get(full) or d.get(base, '')) + '|' + (d.get(full + ':fg') or d.get(base + ':fg', '')) + '|' + (d.get(full + ':bg') or d.get(base + ':bg', '')))",
            rootShell.wallpaperPath.split("/").pop(),
            rootShell.wallpaperPath
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                let parts = this.text.trim().split("|")
                if (parts.length >= 3) {
                    if (parts[0] && parts[0].endsWith(".png")) rootShell.depthPath = parts[0];
                    if (parts[1] && parts[1].endsWith(".png")) rootShell.fgPath = parts[1];
                    if (parts[2] && parts[2].endsWith(".png")) rootShell.bgPath = parts[2];
                }
                if (!rootShell.hasDiscreteLayers && !depthLookupProcess.hasAttempted && rootShell.wallpaperPath !== "") {
                    depthLookupProcess.hasAttempted = true;
                    depthLookupProcess.running = true;
                }
            }
        }
    }

    // Global Hyprland cursor stream (tracks cursor over all windows)
    Process {
        id: cursorTracker
        command: ["python3", Qt.resolvedUrl("scripts/hypr_cursor_stream.py").toString().replace("file://", "")]
        running: true
        stdout: SplitParser {
            splitMarker: "\n"
            onRead: data => {
                let parts = data.trim().split(",")
                if (parts.length === 2) {
                    let cx = parseFloat(parts[0].trim())
                    let cy = parseFloat(parts[1].trim())
                    let scrW = liveWindow.width > 0 ? liveWindow.width : 1920
                    let scrH = liveWindow.height > 0 ? liveWindow.height : 1080
                    if (!isNaN(cx) && !isNaN(cy)) {
                        rootShell.currentOffsetX = (cx / scrW) - 0.5
                        rootShell.currentOffsetY = (cy / scrH) - 0.5
                    }
                }
            }
        }
    }

    MatugenColors {
        id: _theme
    }

    // Auto-detect last wallpaper if not explicitly provided
    Process {
        id: lastWallpaperReader
        command: ["cat", Quickshell.env("HOME") + "/.cache/wallpaper_picker/last_wallpaper"]
        running: rootShell.wallpaperPath === ""
        stdout: StdioCollector {
            onStreamFinished: {
                let txt = this.text.trim()
                if (txt.includes("|")) {
                    let parts = txt.split("|")
                    if (parts.length >= 2 && parts[1]) {
                        rootShell.wallpaperPath = parts[1]
                        depthIndexReader.running = true
                    }
                } else if (txt !== "") {
                    rootShell.wallpaperPath = txt
                    depthIndexReader.running = true
                }
            }
        }
    }

    // Look up or generate discrete layers and depth map for the wallpaper
    Process {
        id: depthLookupProcess
        property bool hasAttempted: false
        running: false
        command: [
            "uv", "run",
            Qt.resolvedUrl("scripts/generate_layers.py").toString().replace("file://", ""),
            rootShell.wallpaperPath
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                depthIndexReader.running = true
            }
        }
    }

    Variants {
        model: Quickshell.screens

        PanelWindow {
            id: liveWindow
            required property var modelData
            visible: true
            screen: modelData

            WlrLayershell.layer: WlrLayer.Background
            WlrLayershell.exclusionMode: ExclusionMode.Ignore
            WlrLayershell.namespace: "qs-live-wallpaper"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

            anchors {
                top: true
                bottom: true
                left: true
                right: true
            }

            color: "transparent"

        // Offscreen Date-Time Widget (Caelestia styled)
        Item {
            id: clockCanvas
            anchors.fill: parent
            visible: false

            property var now: new Date()

            Timer {
                interval: 1000
                running: rootShell.showClock
                repeat: true
                onTriggered: clockCanvas.now = new Date()
            }

            Column {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -parent.height * 0.12
                spacing: 4

                Text {
                    id: timeText
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatTime(clockCanvas.now, "hh:mm")
                    color: _theme.text
                    font.family: "Inter"
                    font.pixelSize: Math.round(liveWindow.height * 0.18)
                    font.weight: Font.DemiBold
                    font.letterSpacing: -2
                }

                Text {
                    id: dateText
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatDate(clockCanvas.now, "dddd, d. MMMM")
                    color: Qt.rgba(_theme.subtext1.r, _theme.subtext1.g, _theme.subtext1.b, 0.85)
                    font.family: "Inter"
                    font.pixelSize: Math.round(liveWindow.height * 0.026)
                    font.weight: Font.Medium
                    font.capitalization: Font.Capitalize
                }
            }
        }

        ShaderEffectSource {
            id: clockTextureSource
            sourceItem: clockCanvas
            hideSource: true
            live: rootShell.showClock
        }

        // =============================================================
        // MODE A: DISCRETE LAYERS SANDWICH (ZERO SHADER ARTIFACTS!)
        // =============================================================
        Item {
            id: discreteLayersContainer
            anchors.fill: parent
            visible: rootShell.hasDiscreteLayers
            opacity: (discreteBg.status === Image.Ready && discreteFg.status === Image.Ready) ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

            // 1. Inpainted Background Layer
            Image {
                id: discreteBg
                source: rootShell.bgPath !== "" ? ("file://" + rootShell.bgPath) : ""
                anchors.centerIn: parent
                width: parent.width * 1.06
                height: parent.height * 1.06
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true

                anchors.horizontalCenterOffset: -(rootShell.currentOffsetX + rootShell.ambientOffsetX) * 14
                anchors.verticalCenterOffset: -(rootShell.currentOffsetY + rootShell.ambientOffsetY) * 10
            }

            // 2. Middle Layer: Caelestia Date-Time Clock
            Item {
                id: discreteClockContainer
                anchors.fill: parent
                visible: rootShell.showClock

                anchors.horizontalCenterOffset: -(rootShell.currentOffsetX + rootShell.ambientOffsetX) * 5
                anchors.verticalCenterOffset: -(rootShell.currentOffsetY + rootShell.ambientOffsetY) * 3

                Column {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -parent.height * 0.12
                    spacing: 4

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Qt.formatTime(clockCanvas.now, "hh:mm")
                        color: _theme.text
                        font.family: "Inter"
                        font.pixelSize: Math.round(liveWindow.height * 0.18)
                        font.weight: Font.DemiBold
                        font.letterSpacing: -2
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: Qt.formatDate(clockCanvas.now, "dddd, d. MMMM")
                        color: Qt.rgba(_theme.subtext1.r, _theme.subtext1.g, _theme.subtext1.b, 0.85)
                        font.family: "Inter"
                        font.pixelSize: Math.round(liveWindow.height * 0.026)
                        font.weight: Font.Medium
                        font.capitalization: Font.Capitalize
                    }
                }
            }

            // 3. Crisp Foreground Layer (Pixel-perfect cutout of the subject)
            Image {
                id: discreteFg
                source: rootShell.fgPath !== "" ? ("file://" + rootShell.fgPath) : ""
                anchors.centerIn: parent
                width: parent.width * 1.06
                height: parent.height * 1.06
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true

                anchors.horizontalCenterOffset: (rootShell.currentOffsetX + rootShell.ambientOffsetX) * 22
                anchors.verticalCenterOffset: (rootShell.currentOffsetY + rootShell.ambientOffsetY) * 15
            }
        }

        // =============================================================
        // MODE B: SINGLE-TEXTURE DEPTH SHADER FALLBACK
        // =============================================================
        Item {
            id: container
            anchors.fill: parent
            visible: !rootShell.hasDiscreteLayers

            Image {
                id: sourceImage
                source: rootShell.wallpaperPath !== "" ? ("file://" + rootShell.wallpaperPath) : ""
                fillMode: Image.PreserveAspectCrop
                anchors.fill: parent
                visible: false
                asynchronous: true
                cache: true
            }

            Image {
                id: depthImage
                source: rootShell.depthPath !== "" ? ("file://" + rootShell.depthPath) : ""
                fillMode: Image.PreserveAspectCrop
                anchors.fill: parent
                visible: false
                asynchronous: true
                cache: true
            }

            // 2.5D Parallax Shader with Depth Occlusion
            ShaderEffect {
                id: parallaxShader
                anchors.fill: parent
                visible: sourceImage.status === Image.Ready && depthImage.status === Image.Ready

                property variant source: sourceImage
                property variant depthMap: depthImage
                property variant clockSource: clockTextureSource

                property point mouseOffset: Qt.point(
                    rootShell.currentOffsetX + rootShell.ambientOffsetX,
                    rootShell.currentOffsetY + rootShell.ambientOffsetY
                )
                property real maxDisplacement: rootShell.maxDisplacement
                property real enableClock: rootShell.showClock ? 1.0 : 0.0
                property real clockDepth: rootShell.clockDepth

                vertexShader: Qt.resolvedUrl("shaders/depth_parallax.vert.qsb")
                fragmentShader: Qt.resolvedUrl("shaders/depth_parallax.frag.qsb")
            }

            // Fallback plain image if depth map is not yet ready
            Image {
                anchors.fill: parent
                source: sourceImage.source
                fillMode: Image.PreserveAspectCrop
                visible: !parallaxShader.visible && sourceImage.status === Image.Ready
            }

            // Desktop MouseArea fallback
            MouseArea {
                id: tracker
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton

                onPositionChanged: (mouse) => {
                    rootShell.currentOffsetX = (mouse.x / width) - 0.5
                    rootShell.currentOffsetY = (mouse.y / height) - 0.5
                }
            }
        }

            Shortcut {
                sequence: "Escape"
                onActivated: Qt.quit()
            }

            Shortcut {
                sequence: "c"
                onActivated: rootShell.showClock = !rootShell.showClock
            }
        }
    }
}

