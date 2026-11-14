// The edit's shots in the order they play, each as wide as it lasts, over a filmstrip of its own footage. Drag a
// shot's edge to trim it (back out into its footage, up to its ends), hold and drag a shot to move it, double-click
// to split it, click to put the playhead there. The view is computed from backend.shots and the zoom alone.
import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: tl
    color: win.theme.raised
    radius: 8
    clip: true

    property real pps: 0                        // pixels per second; 0 fits the edit to the width
    readonly property real scale: pps > 0 ? pps : (backend.duration > 0 ? (width - 24) / backend.duration : 50)
    property int dragging: -1                   // the shot being moved
    property real dragX: 0

    function zoomToShot() {
        const s = win.shots[win.current]
        if (!s) return
        if (pps > 0) { pps = 0; return }
        pps = (width - 24) / Math.max(s.duration, 0.5)
        flick.contentX = Math.max(0, s.at * pps - 12)
    }
    function timeAt(x) { return Math.max(0, (x - 12) / scale) }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: Math.max(width, backend.duration * tl.scale + 24)
        interactive: tl.pps > 0
        boundsBehavior: Flickable.StopAtBounds

        MouseArea {                             // click the strip to put the playhead there
            width: flick.contentWidth; height: flick.height
            onPressed: m => win.step(tl.timeAt(m.x) - win.playhead)
            onPositionChanged: m => { if (pressed) win.step(tl.timeAt(m.x) - win.playhead) }
            onWheel: w => {
                if (w.modifiers & Qt.ControlModifier) {
                    const t = tl.timeAt(w.x)
                    tl.pps = Math.max(5, tl.scale * Math.pow(1.15, w.angleDelta.y / 120))
                    flick.contentX = Math.max(0, t * tl.pps + 12 - (w.x - flick.contentX))
                } else w.accepted = false
            }
        }

        Repeater {
            model: win.shots
            delegate: Item {
                id: block
                required property var modelData
                required property int index
                readonly property var s: modelData
                // A trim being dragged: how far each end has moved, in seconds of footage.
                property real dIn: 0
                property real dOut: 0
                readonly property real shownStart: s.start + dIn
                readonly property real shownDuration: s.duration - dIn + dOut
                x: 12 + s.at * tl.scale + (tl.dragging === index ? tl.dragX : 0) + (handleIn.pressed ? dIn * tl.scale : 0)
                y: 26
                z: tl.dragging === index ? 2 : 1
                width: Math.max(4, shownDuration * tl.scale)
                height: tl.height - 38
                opacity: tl.dragging === index ? 0.8 : 1

                Rectangle {
                    anchors.fill: parent
                    radius: 5
                    color: win.theme.background
                    clip: true
                    Row {                       // the filmstrip: a frame every ~110 px across what the shot shows
                        id: strip
                        anchors.fill: parent
                        readonly property int n: Math.max(1, Math.round(block.width / 110))
                        Repeater {
                            model: block.s.path ? strip.n : 0
                            Image {
                                width: block.width / strip.n; height: strip.height
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                sourceSize.height: 90
                                source: "image://av/thumb/" + (Math.round((block.s.start + (index + 0.5) * block.s.duration / strip.n) * 2) / 2).toFixed(1)
                                        + "/" + encodeURIComponent(block.s.path)
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent; visible: !block.s.path
                        text: block.s.title; color: win.theme.foreground; font.italic: true
                    }
                    Rectangle {
                        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 4
                        width: label.implicitWidth + 8; height: label.implicitHeight + 4; radius: 3
                        color: "#b0000000"
                        Text {
                            id: label; anchors.centerIn: parent; font.pixelSize: 11; color: "white"
                            text: block.s.name + (block.s.framing.turn ? " ⟳" : "") + (block.s.framing.zoom > 1.001 ? " " + block.s.framing.zoom.toFixed(1) + "x" : "")
                        }
                    }
                }
                Rectangle {
                    anchors.fill: parent; radius: 5; color: "transparent"
                    border.width: index === win.current ? 2 : 1
                    border.color: index === win.current ? win.theme.accent : win.theme.selection
                }

                MouseArea {                     // hold, then drag to move; double-click to split; click to seek
                    anchors.fill: parent
                    anchors.leftMargin: 8; anchors.rightMargin: 8
                    pressAndHoldInterval: 250
                    property real from: 0
                    onPressed: m => { from = m.x; win.step(block.s.at + (m.x + 8) / tl.scale - win.playhead) }
                    onPressAndHold: { tl.dragging = block.index; tl.dragX = 0 }
                    onPositionChanged: m => {
                        if (tl.dragging === block.index) tl.dragX = m.x - from
                        else if (pressed) win.step(block.s.at + Math.max(0, m.x + 8) / tl.scale - win.playhead)
                    }
                    onReleased: {
                        if (tl.dragging !== block.index) return
                        const centre = block.s.at + block.s.duration / 2 + tl.dragX / tl.scale
                        let to = win.shots.filter(o => o.index !== block.s.index && o.at + o.duration / 2 < centre).length
                        tl.dragging = -1; tl.dragX = 0
                        if (to !== block.index) backend.move(block.index, to)
                    }
                    onDoubleClicked: m => backend.split(block.index, (m.x + 8) / tl.scale)
                }

                MouseArea {                     // the in handle
                    id: handleIn
                    width: 8; height: parent.height; anchors.left: parent.left
                    cursorShape: Qt.SizeHorCursor; enabled: !!block.s.path
                    property real from: 0
                    onPressed: m => from = mapToItem(tl, m.x, 0).x
                    onPositionChanged: m => {
                        if (!pressed) return
                        const d = (mapToItem(tl, m.x, 0).x - from) / tl.scale
                        block.dIn = Math.min(Math.max(d, -block.s.start), block.s.duration - 1 / block.s.fps)
                    }
                    onReleased: { const a = block.shownStart, b = block.s.start + block.s.duration; block.dIn = 0; backend.trim(block.index, a, b) }
                    Rectangle { anchors.fill: parent; radius: 3; color: parent.containsMouse || parent.pressed ? win.theme.accent : "transparent" }
                    hoverEnabled: true
                }
                MouseArea {                     // the out handle
                    id: handleOut
                    width: 8; height: parent.height; anchors.right: parent.right
                    cursorShape: Qt.SizeHorCursor; enabled: !!block.s.path
                    property real from: 0
                    onPressed: m => from = mapToItem(tl, m.x, 0).x
                    onPositionChanged: m => {
                        if (!pressed) return
                        const d = (mapToItem(tl, m.x, 0).x - from) / tl.scale
                        block.dOut = Math.min(Math.max(d, 1 / block.s.fps - block.s.duration), block.s.length - block.s.start - block.s.duration)
                    }
                    onReleased: { const a = block.s.start, b = block.s.start + block.s.duration + block.dOut; block.dOut = 0; backend.trim(block.index, a, b) }
                    Rectangle { anchors.fill: parent; radius: 3; color: parent.containsMouse || parent.pressed ? win.theme.accent : "transparent" }
                    hoverEnabled: true
                }
            }
        }

        Repeater {                              // the ruler: a tick every few seconds
            model: Math.ceil(backend.duration / tl.tick) + 1
            Text {
                x: 12 + index * tl.tick * tl.scale + 3; y: 4
                text: win.clock(index * tl.tick).replace(/\.00$/, ""); color: win.theme.muted; font.pixelSize: 11
            }
        }

        Rectangle {                             // the playhead
            x: 12 + win.playhead * tl.scale - 1; y: 0
            width: 2; height: flick.height; z: 3
            color: win.theme.accent
        }
    }
    readonly property real tick: [1, 2, 5, 10, 15, 30, 60, 120, 300].find(t => t * scale >= 70) || 600
}
