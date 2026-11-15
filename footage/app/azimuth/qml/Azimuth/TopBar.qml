// The top bar: size.topbar tall on the panel, a line under it. The brand on the left, then the bar's children
// (menus, the app's one field, status, theme) laid out in a row: put an Item { Layout.fillWidth: true } where the
// space goes.
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: bar
    property string tag: ""
    default property alias content: row.data
    implicitHeight: Theme.size.topbar
    color: Theme.panel

    // The bar's own parts are listed here, so the children an app gives it go to the row.
    data: [
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line },
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 18
            Brand { tag: bar.tag }
            RowLayout { id: row; Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8 }
        }
    ]
}
