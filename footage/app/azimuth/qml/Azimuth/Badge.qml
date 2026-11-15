// A badge on media: black scrim at 62 %, radius 2, on-photo text, 4 px in from its corner (tl, tr, bl, br).
// Fixed places: top-left rank or rating, top-right pick or reject, bottom-left name, bottom-right count or duration.
import QtQuick

Rectangle {
    id: badge
    property string text: ""
    property string iconName: ""
    property string corner: "bl"
    readonly property bool atRight: corner === "tr" || corner === "br"
    readonly property bool atBottom: corner === "bl" || corner === "br"
    x: parent ? (atRight ? parent.width - width - 4 : 4) : 0
    y: parent ? (atBottom ? parent.height - height - 4 : 4) : 0
    z: 2
    implicitWidth: row.implicitWidth + 10
    implicitHeight: row.implicitHeight + 6
    radius: 2
    color: Theme.scrim

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 3
        Icon { visible: badge.iconName !== ""; name: badge.iconName; size: 10; color: Theme.onPhoto; anchors.verticalCenter: parent.verticalCenter }
        Label {
            text: badge.text
            color: Theme.onPhoto
            textStyle: "label"; size: 10; weight: Font.DemiBold
        }
    }
}
