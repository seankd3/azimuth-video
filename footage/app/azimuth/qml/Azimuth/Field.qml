// A field: well fill, 1 px line, radius.control; the focus ring offset 1; placeholder in text-3; a clear (x) icon when
// it has text; error text below in reject. label: the label above, in the label style. search: the search icon.
import QtQuick
import QtQuick.Templates as T

Column {
    id: field
    property alias text: input.text
    property alias placeholder: input.placeholderText
    property alias input: input
    property string label: ""
    property string error: ""
    property bool search: false
    property bool clearable: true
    signal accepted()
    spacing: 5
    opacity: enabled ? 1 : 0.4

    Label { visible: field.label !== ""; textStyle: "label"; text: field.label; color: Theme.text3 }
    T.TextField {
        id: input
        width: field.width
        implicitHeight: Theme.size.control
        leftPadding: field.search ? 31 : 9
        rightPadding: field.clearable ? 30 : 9
        hoverEnabled: true
        font: Theme.fonts.body
        color: Theme.text
        placeholderTextColor: Theme.text3
        selectionColor: Theme.selection
        selectedTextColor: Theme.text
        verticalAlignment: TextInput.AlignVCenter
        onAccepted: field.accepted()
        Keys.onEscapePressed: e => { if (text !== "") { text = ""; e.accepted = true } else e.accepted = false }
        background: Rectangle {
            radius: Theme.radius.control
            color: Theme.well
            border.width: 1
            border.color: field.error !== "" ? Theme.reject : input.hovered || input.activeFocus ? Theme.lineStrong : Theme.line
            Behavior on border.color { ColorAnimation { duration: Theme.motion.fast } }
            FocusRing { target: input; offset: 1; showing: input.activeFocus }
        }
        Label {                                      // the placeholder (Templates leave it to the style)
            x: input.leftPadding
            width: input.width - input.leftPadding - input.rightPadding
            anchors.verticalCenter: parent.verticalCenter
            text: input.placeholderText
            color: Theme.text3
            visible: input.text === "" && input.preeditText === ""
        }
        Icon { visible: field.search; name: "search"; color: Theme.text3; x: 9; anchors.verticalCenter: parent.verticalCenter }
        Button {
            visible: field.clearable && input.text !== ""
            anchors.right: parent.right; anchors.rightMargin: 3; anchors.verticalCenter: parent.verticalCenter
            small: true; icon.name: "close"; tip: "Clear"
            onClicked: { input.text = ""; input.forceActiveFocus() }
        }
    }
    Label { visible: field.error !== ""; text: field.error; color: Theme.reject; textStyle: "meta"; width: field.width; wrapMode: Text.Wrap }
}
