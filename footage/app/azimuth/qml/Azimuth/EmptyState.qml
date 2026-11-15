// An empty view: centred in its panel, the compass mark, a heading, one line of meta, and the one way out as a
// primary button ("Open an edit"). Never "No items".
import QtQuick

Column {
    id: empty
    property string title: ""
    property string text: ""
    property string action: ""
    property string actionIcon: ""
    property string actionKey: ""
    signal activated()
    spacing: 8
    width: Math.min(420, parent ? parent.width - 40 : 420)

    Mark { anchors.horizontalCenter: parent.horizontalCenter; size: 24 }
    Item { width: 1; height: 2 }
    Label { anchors.horizontalCenter: parent.horizontalCenter; textStyle: "heading"; text: empty.title
            width: Math.min(implicitWidth, empty.width); horizontalAlignment: Text.AlignHCenter }
    Label { anchors.horizontalCenter: parent.horizontalCenter; textStyle: "body"; text: empty.text; color: Theme.text3
            width: empty.width; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideNone }
    Item { width: 1; height: 6 }
    Button {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: empty.action !== ""
        kind: "primary"; text: empty.action; icon.name: empty.actionIcon; key: empty.actionKey
        onClicked: empty.activated()
    }
}
