// Progress: a 3 px line track, filled in text-2 (go when done, reject when failed). value < 0: indeterminate, a 30 %
// bar sliding at motion.slow.
import QtQuick

Rectangle {
    id: bar
    property real value: -1
    property string status: ""                  // "", "done" or "failed"
    implicitWidth: 200
    implicitHeight: 3
    radius: 2
    color: Theme.line
    clip: true
    Rectangle {
        id: fill
        height: parent.height; radius: 2
        width: bar.status === "done" ? bar.width : bar.value < 0 ? bar.width * 0.3 : bar.width * Math.min(1, bar.value)
        color: bar.status === "done" ? Theme.go : bar.status === "failed" ? Theme.reject : Theme.text2
        Behavior on width { enabled: bar.value >= 0; NumberAnimation { duration: Theme.motion.base } }
        NumberAnimation on x {
            running: bar.value < 0 && bar.status === "" && bar.visible
            from: -bar.width * 0.3; to: bar.width
            duration: Theme.motion.slow * 6
            loops: Animation.Infinite
            easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.ease
            onRunningChanged: if (!running) fill.x = 0
        }
    }
}
