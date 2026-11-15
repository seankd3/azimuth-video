// The timeline's ruler: a tick ladder in text-3 and times in mono, every `tick` seconds (the first of 1, 2, 5, 10,
// 15, 30, 60... that leaves room for a label), with four minor ticks between. pixelsPerSecond and origin (the x of
// time 0) place it; fromX/toX limit drawing to what is in view.
import QtQuick

Item {
    id: ruler
    property real pixelsPerSecond: 50
    property real origin: 0
    property real duration: 0
    property real fromX: 0
    property real toX: width
    readonly property real tick: [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].find(t => t * pixelsPerSecond >= 70) || 7200
    readonly property real minor: tick / 5
    implicitHeight: 22

    function clock(t) {
        const s = Math.round(t), pad = n => (n < 10 ? "0" : "") + n
        return s >= 3600 ? Math.floor(s / 3600) + ":" + pad(Math.floor(s / 60) % 60) + ":" + pad(s % 60)
                         : pad(Math.floor(s / 60)) + ":" + pad(s % 60)
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    Repeater {                                       // minor ticks, 5 px tall at the foot
        model: {
            const first = Math.max(0, Math.floor((ruler.fromX - ruler.origin) / (ruler.minor * ruler.pixelsPerSecond)))
            const last = Math.ceil((ruler.toX - ruler.origin) / (ruler.minor * ruler.pixelsPerSecond))
            return Math.max(0, Math.min(last - first + 1, 2000))
        }
        Rectangle {
            required property int index
            readonly property int n: Math.max(0, Math.floor((ruler.fromX - ruler.origin) / (ruler.minor * ruler.pixelsPerSecond))) + index
            x: ruler.origin + n * ruler.minor * ruler.pixelsPerSecond
            y: ruler.height - height - 1
            width: 1
            height: n % 5 === 0 ? 9 : 5
            color: Theme.lineStrong
        }
    }
    Repeater {                                       // labelled ticks
        model: {
            const first = Math.max(0, Math.floor((ruler.fromX - ruler.origin) / (ruler.tick * ruler.pixelsPerSecond)))
            const last = Math.ceil((ruler.toX - ruler.origin) / (ruler.tick * ruler.pixelsPerSecond))
            return Math.max(0, Math.min(last - first + 1, 400))
        }
        Label {
            required property int index
            readonly property int n: Math.max(0, Math.floor((ruler.fromX - ruler.origin) / (ruler.tick * ruler.pixelsPerSecond))) + index
            x: ruler.origin + n * ruler.tick * ruler.pixelsPerSecond + 3
            y: 3
            text: ruler.clock(n * ruler.tick)
            color: Theme.text3
            textStyle: "code"
            size: 10
            verticalAlignment: Text.AlignTop
            elide: Text.ElideNone
        }
    }
}
