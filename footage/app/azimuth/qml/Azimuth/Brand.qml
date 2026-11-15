// The brand: the mark, the wordmark and the inverted product tag. The apps differ only in the tag.
import QtQuick

Row {
    id: brand
    property string tag: ""
    spacing: 8
    Mark { size: 18; color: Theme.text; anchors.verticalCenter: parent.verticalCenter }
    Label { textStyle: "wordmark"; text: "Azimuth"; anchors.verticalCenter: parent.verticalCenter }
    Rectangle {
        visible: brand.tag !== ""
        anchors.verticalCenter: parent.verticalCenter
        width: tagLabel.implicitWidth + 10; height: tagLabel.implicitHeight + 4
        radius: 2
        color: Theme.text
        Label { id: tagLabel; anchors.centerIn: parent; textStyle: "tag"; text: brand.tag; color: Theme.panel }
    }
}
