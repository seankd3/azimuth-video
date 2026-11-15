// A key cap: code at 10.5 px, 1 px line-strong with a 2 px bottom, panel-raised fill.
import QtQuick

Rectangle {
    id: cap
    property string text: ""
    property bool inButton: false        // inside a button: the button's ink, no fill
    property color ink: Theme.text2
    implicitHeight: inButton ? 16 : 18
    implicitWidth: Math.max(implicitHeight, label.implicitWidth + 8)
    radius: Theme.radius.control
    color: inButton ? ink : Theme.lineStrong
    opacity: inButton ? 0.7 : 1
    Rectangle {
        x: 1; y: 1; width: parent.width - 2; height: parent.height - (cap.inButton ? 2 : 3)
        radius: Math.max(0, Theme.radius.control - 1)
        color: cap.inButton ? cap.parentFill : Theme.panelRaised
    }
    property color parentFill: Theme.panel
    Label {
        id: label
        anchors.centerIn: parent
        anchors.verticalCenterOffset: cap.inButton ? 0 : -0.5
        text: cap.text
        color: cap.ink
        textStyle: "code"; size: 10.5; weight: Font.Medium
    }
}
