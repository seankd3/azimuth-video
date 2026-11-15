// A panel: panel body, radius.panel, 1 px line, on the canvas with size.gutter between panels. No shadow.
import QtQuick

Rectangle {
    color: Theme.panel
    radius: Theme.radius.panel
    border.width: 1
    border.color: Theme.line
}
