// A select: a quiet button with its value and a chevron, opening a menu on a float (never a native list).
// Use it as a ComboBox: model, currentIndex, textRole, activated(index).
import QtQuick
import QtQuick.Templates as T

T.ComboBox {
    id: box
    implicitWidth: 180
    implicitHeight: Theme.size.control
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    opacity: enabled ? 1 : 0.4
    leftPadding: 10
    rightPadding: 28

    background: Rectangle {
        radius: Theme.radius.control
        color: Theme.panel
        border.width: 1
        border.color: box.hovered || box.popup.visible ? Theme.lineHover : Theme.lineStrong
        Behavior on border.color { ColorAnimation { duration: Theme.motion.fast } }
        FocusRing { target: box }
    }
    contentItem: Label { text: box.displayText; textStyle: "body" }
    indicator: Icon {
        x: box.width - width - 9
        y: (box.height - height) / 2
        size: 12
        name: "chevron-down"
        color: Theme.text2
    }
    delegate: T.ItemDelegate {
        id: row
        required property int index
        width: ListView.view ? ListView.view.width : 0
        height: Theme.size.row
        hoverEnabled: true
        highlighted: box.highlightedIndex === index
        leftPadding: 9; rightPadding: 9
        contentItem: Item {
            Label { anchors.verticalCenter: parent.verticalCenter; width: parent.width - 20; text: box.textAt(row.index) }
            Icon { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; size: 12; name: "check"
                   color: Theme.text2; visible: row.index === box.currentIndex }
        }
        background: Rectangle { radius: Theme.radius.control; color: row.highlighted || row.hovered ? Theme.rowHover : "transparent" }
    }
    popup: T.Popup {
        y: box.height + 4
        width: Math.max(box.width, 180)
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 360)
        padding: 4
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Theme.motion.base } }
        contentItem: ListView {
            implicitHeight: contentHeight
            clip: true
            model: box.popup.visible ? box.delegateModel : null
            currentIndex: box.highlightedIndex
        }
        background: Float {}
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
