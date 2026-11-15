// A tooltip: after 500 ms, label style, on a float, no arrow. Give it the control's name and key ("Split · S").
import QtQuick
import QtQuick.Templates as T

T.ToolTip {
    id: tip
    delay: 500
    y: parent ? parent.height + 6 : 0
    x: parent ? (parent.width - width) / 2 : 0
    padding: 0
    margins: 6
    contentItem: Label {
        text: tip.text
        leftPadding: 7; rightPadding: 7; topPadding: 4; bottomPadding: 4
        textStyle: "label"; caps: 0
    }
    background: Rectangle {
        color: Theme.float; radius: Theme.radius.control
        border.width: 1; border.color: Theme.lineStrong
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motion.fast } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Theme.motion.fast } }
}
