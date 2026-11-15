// The one focus ring: 2 px in the theme's focus colour, offset 2 (1 inside fields), shown for keyboard focus only.
// Put it inside a control; it follows `target` (the parent) and shows when target.visualFocus.
import QtQuick

Rectangle {
    property Item target: parent
    property real offset: 2
    property real targetRadius: Theme.radius.control
    property bool showing: !!target && !!target.visualFocus
    x: -offset - 2; y: -offset - 2
    width: (target ? target.width : 0) + 2 * (offset + 2)
    height: (target ? target.height : 0) + 2 * (offset + 2)
    radius: targetRadius + offset + 2
    color: "transparent"
    border.width: 2
    border.color: Theme.focus
    visible: showing
    z: 10
}
