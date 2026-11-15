// The edit's shots in the order they play, each as wide as it lasts, over a filmstrip of its own footage, on the
// design system's ruler, clips and playhead. Drag a shot's edge to trim it (back out into its footage, up to its ends),
// hold and drag a shot to move it, click to put the playhead there, double-click to fit the timeline to the shot.
// Ctrl+wheel zooms time. The view is computed from backend.shots and the zoom alone.
import QtQuick
import Azimuth as Az

Rectangle {
    id: tl
    color: Az.Theme.well
    radius: Az.Theme.radius.panel
    clip: true

    property real pps: 0                        // pixels per second; 0 fits the edit to the width
    readonly property real pad: 12
    readonly property real scale: pps > 0 ? pps : (backend.duration > 0 ? (width - 2 * pad) / backend.duration : 50)
    property int dragging: -1                   // the shot being moved
    property real dragX: 0

    function zoomToShot() {
        const s = win.shots[win.current]
        if (!s) return
        if (pps > 0) { pps = 0; return }
        pps = (width - 2 * pad) / Math.max(s.duration, 0.5)
        flick.contentX = Math.max(0, s.at * pps - pad)
    }
    function timeAt(x) { return Math.max(0, (x - pad) / scale) }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: Math.max(width, backend.duration * tl.scale + 2 * tl.pad)
        interactive: tl.pps > 0
        boundsBehavior: Flickable.StopAtBounds

        Az.TimelineRuler {
            id: ruler
            width: flick.contentWidth
            pixelsPerSecond: tl.scale
            origin: tl.pad
            duration: backend.duration
            fromX: flick.contentX
            toX: flick.contentX + flick.width
        }

        MouseArea {                             // click the strip to put the playhead there
            width: flick.contentWidth; height: flick.height
            onPressed: m => win.step(tl.timeAt(m.x) - win.playhead)
            onPositionChanged: m => { if (pressed) win.step(tl.timeAt(m.x) - win.playhead) }
            onWheel: w => {
                if (w.modifiers & Qt.ControlModifier) {
                    const t = tl.timeAt(w.x)
                    tl.pps = Math.max(5, tl.scale * Math.pow(1.15, w.angleDelta.y / 120))
                    flick.contentX = Math.max(0, t * tl.pps + tl.pad - (w.x - flick.contentX))
                } else w.accepted = false
            }
        }

        Repeater {
            model: win.shots
            delegate: Az.Clip {
                id: block
                required property var modelData
                required property int index
                readonly property var s: modelData
                // A trim being dragged: how far each end has moved, in seconds of footage.
                property real dIn: 0
                property real dOut: 0
                readonly property real shownStart: s.start + dIn
                readonly property real shownDuration: s.duration - dIn + dOut
                x: tl.pad + s.at * tl.scale + (tl.dragging === index ? tl.dragX : 0) + dIn * tl.scale
                y: ruler.height + 6
                z: tl.dragging === index ? 2 : 1
                width: Math.max(4, shownDuration * tl.scale)
                height: tl.height - y - 8
                opacity: tl.dragging === index ? 0.8 : 1
                current: index === win.current
                trimmable: !!s.path
                label: s.path ? s.name + (s.framing.zoom > 1.001 ? " " + s.framing.zoom.toFixed(1) + "×" : "") : ""
                labelIcon: s.path && s.framing.turn ? "rotate-right" : ""

                onTrimMoved: (end, dx) => {
                    const d = dx / tl.scale
                    if (end === "in") dIn = Math.min(Math.max(d, -s.start), s.duration - 1 / s.fps)
                    else dOut = Math.min(Math.max(d, 1 / s.fps - s.duration), s.length - s.start - s.duration)
                }
                onTrimEnded: end => {
                    const a = end === "in" ? shownStart : s.start
                    const b = end === "in" ? s.start + s.duration : s.start + s.duration + dOut
                    dIn = 0; dOut = 0
                    backend.trim(index, a, b)
                }

                Row {                           // the filmstrip: a frame every ~110 px across what the shot shows
                    id: strip
                    anchors.fill: parent
                    readonly property int n: Math.max(1, Math.round(block.width / 110))
                    Repeater {
                        model: block.s.path ? strip.n : 0
                        Image {
                            required property int index
                            width: block.width / strip.n; height: strip.height
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            sourceSize.height: 90
                            source: "image://av/thumb/" + (Math.round((block.s.start + (index + 0.5) * block.s.duration / strip.n) * 2) / 2).toFixed(1)
                                    + "/" + encodeURIComponent(block.s.path)
                        }
                    }
                }
                Az.Label {                       // a title card
                    anchors.centerIn: parent
                    width: parent.width - 12
                    horizontalAlignment: Text.AlignHCenter
                    visible: !block.s.path
                    textStyle: "meta"; color: Az.Theme.text2
                    text: block.s.title
                }
                MouseArea {                     // hold, then drag to move; click to seek; double-click fits the shot
                    anchors.fill: parent
                    anchors.leftMargin: 6; anchors.rightMargin: 6
                    pressAndHoldInterval: 250
                    property real from: 0
                    onPressed: m => { from = m.x; win.step(block.s.at + (m.x + 6) / tl.scale - win.playhead) }
                    onPressAndHold: { tl.dragging = block.index; tl.dragX = 0 }
                    onPositionChanged: m => {
                        if (tl.dragging === block.index) tl.dragX = m.x - from
                        else if (pressed) win.step(block.s.at + Math.max(0, m.x + 6) / tl.scale - win.playhead)
                    }
                    onReleased: {
                        if (tl.dragging !== block.index) return
                        const centre = block.s.at + block.s.duration / 2 + tl.dragX / tl.scale
                        let to = win.shots.filter(o => o.index !== block.s.index && o.at + o.duration / 2 < centre).length
                        tl.dragging = -1; tl.dragX = 0
                        if (to !== block.index) backend.move(block.index, to)
                    }
                    onDoubleClicked: { tl.pps = 0; tl.zoomToShot() }
                }
            }
        }

        Az.Playhead { position: tl.pad + win.playhead * tl.scale; height: flick.height }
    }
}
