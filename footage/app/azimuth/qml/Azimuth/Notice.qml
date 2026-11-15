// A notice: an inline strip in the panel it concerns, until resolved. A 2 px leading bar and the title in the meaning
// colour (info, warn, reject), body text, an optional action. For "low disk", "camera not found", "offline".
import QtQuick

Rectangle {
    id: notice
    property string meaning: "info"
    property string title: ""
    property string text: ""
    property string action: ""
    property string iconName: meaning === "info" ? "info" : "warning"
    signal activated()
    readonly property color tone: meaning === "warn" ? Theme.warn : meaning === "reject" ? Theme.reject : Theme.info
    implicitWidth: 320
    implicitHeight: Math.max(body.implicitHeight, act.implicitHeight) + 18
    radius: Theme.radius.control
    color: Theme.panelRaised
    clip: true

    Rectangle { width: 2; height: parent.height; color: notice.tone }
    Icon { x: 11; y: 10; name: notice.iconName; color: notice.tone }
    Column {
        id: body
        x: 37; y: 9
        width: parent.width - x - (act.visible ? act.width + 20 : 11)
        spacing: 2
        Label { textStyle: "eyebrow"; text: notice.title; color: notice.tone; visible: notice.title !== "" }
        Label { text: notice.text; wrapMode: Text.Wrap; width: parent.width; elide: Text.ElideNone }
    }
    Button {
        id: act
        visible: notice.action !== ""
        anchors.right: parent.right; anchors.rightMargin: 9; y: 9
        small: true; text: notice.action
        onClicked: notice.activated()
    }
}
