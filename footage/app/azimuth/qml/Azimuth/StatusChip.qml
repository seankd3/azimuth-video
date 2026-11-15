// A status chip: pill, label style, a 6 px light, the word, an optional pace ("4.2/s").
// light: idle (text-3), working (go), live (reject, pulsing 1.4 s), attention (warn), fault (reject).
import QtQuick

Rectangle {
    id: chip
    property string light: "idle"
    property string text: ""
    property string pace: ""
    implicitHeight: Theme.size.control_small
    implicitWidth: row.implicitWidth + 18
    radius: height / 2
    color: "transparent"
    border.width: 1
    border.color: Theme.line

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7
        Rectangle {
            id: dot
            width: 6; height: 6; radius: 3
            anchors.verticalCenter: parent.verticalCenter
            color: chip.light === "working" ? Theme.go
                 : chip.light === "live" || chip.light === "fault" ? Theme.reject
                 : chip.light === "attention" ? Theme.warn : Theme.text3
            SequentialAnimation on opacity {
                running: chip.light === "live" && chip.visible
                loops: Animation.Infinite
                onRunningChanged: if (!running) dot.opacity = 1
                NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
            }
        }
        Label { textStyle: "label"; text: chip.text; color: Theme.text2 }
        Label { textStyle: "label"; text: "· " + chip.pace; color: Theme.text2; visible: chip.pace !== "" }
    }
}
