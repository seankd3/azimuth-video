// Joined choices for 2-5 exclusive options; the chosen one is "on". model: strings, or {text, icon, tip}.
// currentIndex: the chosen one (-1: none). activated(index) when one is clicked.
import QtQuick
import QtQuick.Templates as T

Rectangle {
    id: seg
    property var model: []
    property int currentIndex: -1
    property bool small: false
    signal activated(int index)

    implicitWidth: row.implicitWidth + 2
    implicitHeight: small ? Theme.size.control_small : Theme.size.control
    color: Theme.lineStrong
    radius: Theme.radius.control
    opacity: enabled ? 1 : 0.4

    Row {
        id: row
        x: 1; y: 1
        spacing: 1
        Repeater {
            id: rep
            model: seg.model
            delegate: T.AbstractButton {
                id: choice
                required property var modelData
                required property int index
                readonly property string label: typeof modelData === "string" ? modelData : (modelData.text || "")
                readonly property string iconName: typeof modelData === "string" ? "" : (modelData.icon || "")
                readonly property bool on: index === seg.currentIndex
                readonly property bool first: index === 0
                readonly property bool last: index === rep.count - 1
                height: seg.height - 2
                implicitWidth: Math.max(height, inner.implicitWidth + (seg.small ? 16 : 20))
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                onClicked: seg.activated(index)
                background: Rectangle {
                    readonly property real r: Math.max(0, Theme.radius.control - 1)
                    topLeftRadius: choice.first ? r : 0; bottomLeftRadius: choice.first ? r : 0
                    topRightRadius: choice.last ? r : 0; bottomRightRadius: choice.last ? r : 0
                    color: choice.on ? Theme.accent : choice.hovered ? Theme.rowHover : Theme.panel
                    Behavior on color { ColorAnimation { duration: Theme.motion.fast } }
                    FocusRing { target: choice }
                }
                contentItem: Item {
                    Row {
                        id: inner
                        anchors.centerIn: parent
                        spacing: 6
                        Icon { visible: choice.iconName !== ""; name: choice.iconName; anchors.verticalCenter: parent.verticalCenter
                               color: choice.on ? Theme.accentInk : choice.hovered ? Theme.text : Theme.text2 }
                        Label { visible: choice.label !== ""; textStyle: "button"; text: choice.label; anchors.verticalCenter: parent.verticalCenter
                                color: choice.on ? Theme.accentInk : choice.hovered ? Theme.text : Theme.text2 }
                    }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                Tip { text: typeof choice.modelData === "string" ? "" : (choice.modelData.tip || ""); visible: text !== "" && choice.hovered }
            }
        }
    }
}
