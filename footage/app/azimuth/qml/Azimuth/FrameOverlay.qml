// The one frame and crop overlay: crop (Photo, Tethered) and reframe (Video). Outside the frame black at 60 %; the
// frame 1 px on-photo at 85 %; 8 handles (L-corners 12 px, edge bars 16x3); rule-of-thirds lines at 30 % while
// dragging. frame: the frame's rectangle in this item. The overlay's children sit over the dimmed picture and under
// the handles (a MouseArea there pans); `bar` holds aspect chips and actions, under the frame on a float.
// A handle drag reports handleStarted(name), handleMoved(name, dx, dy) in pixels, handleEnded(name); names are
// nw n ne e se s sw w.
import QtQuick

Item {
    id: overlay
    property rect frame: Qt.rect(0, 0, width, height)
    property bool dragging: false
    property bool handles: true
    default property alias content: under.data
    property alias bar: barRow.data
    signal handleStarted(string name)
    signal handleMoved(string name, real dx, real dy)
    signal handleEnded(string name)
    readonly property bool resizing: handleLayer.busy

    readonly property color dim: Theme.alpha("black", 0.6)
    // Whole pixels, so the four dimmed sides meet without a darker seam.
    readonly property real fx: Math.round(frame.x)
    readonly property real fy: Math.round(frame.y)
    readonly property real fw: Math.round(frame.x + frame.width) - fx
    readonly property real fh: Math.round(frame.y + frame.height) - fy

    // The overlay's own parts are listed here, so the children an app gives it go over the picture, under the handles.
    data: [
        Rectangle { x: 0; y: 0; width: overlay.width; height: Math.max(0, overlay.fy); color: overlay.dim },
        Rectangle { x: 0; y: overlay.fy + overlay.fh; width: overlay.width; height: Math.max(0, overlay.height - y); color: overlay.dim },
        Rectangle { x: 0; y: overlay.fy; width: Math.max(0, overlay.fx); height: overlay.fh; color: overlay.dim },
        Rectangle { x: overlay.fx + overlay.fw; y: overlay.fy; width: Math.max(0, overlay.width - x); height: overlay.fh; color: overlay.dim },

        Item {                                           // the thirds, while dragging
            x: overlay.fx; y: overlay.fy; width: overlay.fw; height: overlay.fh
            opacity: overlay.dragging || overlay.resizing ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.motion.fast } }
            Repeater {
                model: 2
                Rectangle { required property int index; x: (index + 1) * parent.width / 3; width: 1; height: parent.height; color: Theme.alpha(Theme.onPhoto, 0.3) }
            }
            Repeater {
                model: 2
                Rectangle { required property int index; y: (index + 1) * parent.height / 3; height: 1; width: parent.width; color: Theme.alpha(Theme.onPhoto, 0.3) }
            }
        },
        Rectangle {                                      // the frame
            x: overlay.fx - 1; y: overlay.fy - 1; width: overlay.fw + 2; height: overlay.fh + 2
            color: "transparent"
            border.width: 1
            border.color: Theme.alpha(Theme.onPhoto, 0.85)
        },

        Item { id: under; anchors.fill: parent },

        Item {
            id: handleLayer
            anchors.fill: parent
            visible: overlay.handles
            property bool busy: false
            Repeater {
                model: ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
                Item {
                    id: h
                    required property string modelData
                    readonly property bool corner: modelData.length === 2
                    readonly property bool atLeft: modelData.indexOf("w") >= 0
                    readonly property bool atRight: modelData.indexOf("e") >= 0
                    readonly property bool atTop: modelData.indexOf("n") >= 0
                    readonly property bool atBottom: modelData.indexOf("s") >= 0
                    readonly property real cx: atLeft ? overlay.fx : atRight ? overlay.fx + overlay.fw : overlay.fx + overlay.fw / 2
                    readonly property real cy: atTop ? overlay.fy : atBottom ? overlay.fy + overlay.fh : overlay.fy + overlay.fh / 2
                    x: cx - 12; y: cy - 12; width: 24; height: 24
                    // The drawn mark: an L at a corner, a bar on an edge, 3 px thick, 2 px outside the frame line.
                    Rectangle {                          // horizontal stroke (corners, and the n/s bars)
                        visible: h.corner || h.atTop || h.atBottom
                        width: h.corner ? 12 : 16; height: 3
                        x: h.corner ? (h.atLeft ? 12 - 2 : 12 + 2 - width) : 12 - width / 2
                        y: h.atTop ? 12 - 2 : 12 + 2 - height
                        color: Theme.onPhoto
                    }
                    Rectangle {                          // vertical stroke (corners, and the e/w bars)
                        visible: h.corner || h.atLeft || h.atRight
                        width: 3; height: h.corner ? 12 : 16
                        x: h.atLeft ? 12 - 2 : 12 + 2 - width
                        y: h.corner ? (h.atTop ? 12 - 2 : 12 + 2 - height) : 12 - height / 2
                        color: Theme.onPhoto
                    }
                    MouseArea {
                        anchors.fill: parent
                        preventStealing: true
                        cursorShape: h.corner ? ((h.atLeft === h.atTop) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor)
                                              : (h.atLeft || h.atRight) ? Qt.SizeHorCursor : Qt.SizeVerCursor
                        property point from
                        onPressed: m => { from = mapToItem(overlay, m.x, m.y); handleLayer.busy = true; overlay.handleStarted(h.modelData) }
                        onPositionChanged: m => {
                            if (!pressed) return
                            const p = mapToItem(overlay, m.x, m.y)
                            overlay.handleMoved(h.modelData, p.x - from.x, p.y - from.y)
                        }
                        onReleased: { handleLayer.busy = false; overlay.handleEnded(h.modelData) }
                    }
                }
            }
        },

        Item {                                           // the bar: aspect chips and actions, at the foot
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom; anchors.bottomMargin: 12
            width: barRow.implicitWidth + 8; height: barRow.implicitHeight + 8
            visible: barRow.children.length > 0
            z: 5
            Float { anchors.fill: parent; color: Theme.alpha(Theme.panel, 0.82); edge: Theme.line; shadow: false }
            Row { id: barRow; x: 4; y: 4; spacing: 6 }
        }
    ]
}
