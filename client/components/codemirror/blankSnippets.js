import { EditorSelection, Prec, StateEffect, StateField } from "@codemirror/state";
import { keymap } from "@codemirror/view";

// Field value: { blanks: [{ from, to }, ...], active: number }. `active` is
// tracked explicitly rather than re-derived from the current selection —
// once the user types, the cursor moves away from the blank's original
// position, so matching against the live selection would lose track of
// which blank is "current" after a single keystroke.
const setBlankState = StateEffect.define();

const blankField = StateField.define({
  create() {
    return { blanks: [], active: -1 };
  },
  update(state, tr) {
    for (const effect of tr.effects) {
      if (effect.is(setBlankState)) {
        state = effect.value;
      }
    }
    if (state.blanks.length > 0 && !tr.changes.empty) {
      state = {
        active: state.active,
        blanks: state.blanks.map((b) => ({
          from: tr.changes.mapPos(b.from, -1),
          to: tr.changes.mapPos(b.to, 1),
        })),
      };
    }
    return state;
  },
});

// Places a collapsed cursor at the start of the blank rather than selecting
// its label text: this editor only mounts in vim mode, and vim's Normal
// mode doesn't treat a plain CM6 selection as "type to replace" the way a
// GUI editor does (codemirror-vim tracks visual-mode state separately from
// raw CM6 selection, and typing a character in Visual mode isn't "replace"
// anyway — it's a different vim command like c/d/y). Landing the cursor at
// the blank and letting the user drive with their own vim commands from
// there is the idiomatic fit.
function jumpToBlank(view, index) {
  const { blanks } = view.state.field(blankField);
  if (index < 0 || index >= blanks.length) {
    return false;
  }
  view.dispatch({
    effects: setBlankState.of({ blanks, active: index }),
    selection: EditorSelection.cursor(blanks[index].from),
    scrollIntoView: true,
  });
  return true;
}

// Ends the session (so Tab falls through to vim/default handling again)
// once the user moves past the first or last blank.
function endSession(view) {
  view.dispatch({ effects: setBlankState.of({ blanks: [], active: -1 }) });
}

function advanceBlank(view) {
  const { blanks, active } = view.state.field(blankField);
  if (blanks.length === 0) {
    return false;
  }
  const next = active + 1;
  if (next >= blanks.length) {
    endSession(view);
    return false;
  }
  return jumpToBlank(view, next);
}

function retreatBlank(view) {
  const { blanks, active } = view.state.field(blankField);
  if (blanks.length === 0) {
    return false;
  }
  const prev = active - 1;
  if (prev < 0) {
    endSession(view);
    return false;
  }
  return jumpToBlank(view, prev);
}

// vim() must still get first refusal on every other keypress. Tab/Enter/
// Shift-Tab are only intercepted here while a blank session is active
// (advanceBlank/retreatBlank return false otherwise), so Prec.highest only
// pre-empts vim for the duration of that session, not permanently.
export const blankSnippets = [
  blankField,
  Prec.highest(
    keymap.of([
      { key: "Tab", run: advanceBlank },
      { key: "Enter", run: advanceBlank },
      { key: "Shift-Tab", run: retreatBlank },
    ]),
  ),
];

export function startBlankSession(view, blanks) {
  if (!blanks || blanks.length === 0) {
    return;
  }
  const mapped = blanks.map((b) => ({ from: b.start, to: b.end }));
  view.dispatch({
    effects: setBlankState.of({ blanks: mapped, active: 0 }),
    selection: EditorSelection.cursor(mapped[0].from),
    scrollIntoView: true,
  });
  view.focus();
}
