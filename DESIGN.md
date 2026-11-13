---
name: LLMoxie console
description:
  The SSEC design system applied to a three-role administration console.
colors:
  primary: "#4b2e83"
  primary-hover: "#32006e"
  primary-foreground: "#ffffff"
  secondary: "#f0ecf7"
  signature: "#2ad2c9"
  nav: "#32006e"
  nav-foreground: "#e8e3d3"
  nav-muted: "#b7a57a"
  terminal: "#1a0038"
  page: "#f9f7f2"
  card: "#ffffff"
  foreground: "#1a1d1f"
  muted-foreground: "#555a5e"
  muted: "#f6f7f8"
  border: "#d5d8de"
  destructive: "#c62828"
  bad-surface: "#ffebee"
  good: "#2e7d32"
typography:
  display:
    fontFamily:
      "Encode Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI,
      Roboto, sans-serif"
    fontSize: "clamp(1.5rem, 1.3rem + 1vw, 2rem)"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.015em"
  headline:
    fontFamily:
      "Encode Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI,
      Roboto, sans-serif"
    fontSize: "clamp(1.5rem, 1.3rem + 1vw, 2rem)"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.015em"
  title:
    fontFamily:
      "Encode Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI,
      Roboto, sans-serif"
    fontSize: "clamp(1.125rem, 1.05rem + 0.375vw, 1.25rem)"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily:
      "Open Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto,
      sans-serif"
    fontSize: "clamp(1rem, 0.95rem + 0.25vw, 1.0625rem)"
    fontWeight: 400
    lineHeight: 1.625
  body-sm:
    fontFamily:
      "Open Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto,
      sans-serif"
    fontSize: "clamp(0.875rem, 0.825rem + 0.25vw, 0.9375rem)"
    fontWeight: 400
  label:
    fontFamily:
      "Encode Sans Variable, -apple-system, BlinkMacSystemFont, Segoe UI,
      sans-serif"
    fontSize: "clamp(0.75rem, 0.7rem + 0.25vw, 0.8125rem)"
    fontWeight: 600
    letterSpacing: "0.05em"
    fontVariation: '"wdth" 75'
  mono:
    fontFamily:
      "JetBrains Mono Variable, Fira Code, Source Code Pro, Consolas, monospace"
    fontSize: "clamp(0.875rem, 0.825rem + 0.25vw, 0.9375rem)"
    fontWeight: 500
rounded:
  none: "0"
  sm: "4px"
  md: "8px"
  xl: "12px"
  full: "9999px"
spacing:
  "1.5": "6px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "8": "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.none}"
    height: "40px"
    padding: "0 20px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    rounded: "{rounded.none}"
    height: "40px"
    padding: "0 20px"
  button-outline-hover:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.primary}"
    rounded: "{rounded.none}"
    height: "32px"
    padding: "0 12px"
  button-ghost-hover:
    backgroundColor: "{colors.secondary}"
  button-destructive:
    backgroundColor: "{colors.destructive}"
    textColor: "{colors.primary-foreground}"
    rounded: "{rounded.none}"
    height: "40px"
    padding: "0 20px"
  button-inverse:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    rounded: "{rounded.none}"
    height: "32px"
    padding: "0 12px"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    padding: "24px"
  stat:
    backgroundColor: "{colors.card}"
    textColor: "{colors.primary}"
    typography: "{typography.display}"
    padding: "20px 24px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.md}"
    height: "44px"
    padding: "10px 12px"
  nav-item:
    backgroundColor: "{colors.nav}"
    textColor: "{colors.nav-foreground}"
    rounded: "{rounded.md}"
    height: "40px"
    padding: "8px 12px"
  nav-item-current:
    textColor: "{colors.primary-foreground}"
  tab:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
    padding: "12px 0"
  tab-current:
    textColor: "{colors.primary}"
  tag:
    backgroundColor: "transparent"
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.xl}"
    padding: "2px 8px"
  tag-bad:
    backgroundColor: "{colors.bad-surface}"
    textColor: "{colors.destructive}"
  code-block:
    backgroundColor: "{colors.terminal}"
    textColor: "{colors.signature}"
    typography: "{typography.mono}"
    rounded: "{rounded.md}"
    padding: "12px 16px"
  dialog:
    backgroundColor: "{colors.card}"
    textColor: "{colors.foreground}"
    rounded: "{rounded.xl}"
    padding: "24px"
    width: "32rem"
---

# Design System: LLMoxie console

## Overview

**Creative North Star: "The Working Ledger"**

The console does not have a visual identity of its own. It is the SSEC design
system (University of Washington Scientific Software Engineering Center) applied
to an administration tool. Every colour, type size, line height and letter
spacing comes from a pinned, unmodified copy of the upstream tokens at
`services/console/frontend/src/styles/ssec-tokens.css` (upstream
`design-system/01-tokens.css`, branch `staging`, commit `d3f017b`, 2026-09-11).
Upstream marks that system alpha, which is why the copy is pinned. The values in
the frontmatter above are that copy's values under the names the console's theme
gives them (`src/index.css`); they are a record, and the token file stays the
source. To change a value, re-copy the token file; do not edit it and do not
restate a value by hand.

What this document adds is how the console uses the system: a Husky Purple
sidebar, a white top bar, and a warm gold ground carrying white cards. The pages
are ledgers. Figures sit in one divided strip, lists are tables, and the form
that adds to a list sits in its own card beside it. Density is moderate: 14 to
15px table text, 24px between cards, 24px inside them. Three roles use the same
shell and the same components; a screen differs by what it lists, never by how
it looks.

The system is light theme only. Nothing sets the `dark` class, and the theme's
`dark:` variant is tied to that class so that the operating system's setting
changes nothing. No chart, sparkline or trend chip exists, because the data
behind one does not exist yet. The content security policy allows no inline
style and no style element added at run time, so overlays are built on the
browser's own `<dialog>` element and the select is the browser's own `<select>`.

**Key Characteristics:**

- A pinned copy of upstream tokens; the console defines no colours of its own.
- One shell for every signed-in screen: 256px sidebar, 56px top bar, page.
- One signature: a 2px teal line that marks where you are.
- Square buttons, 8px cards, hairline borders, almost no shadow.
- Uppercase compressed Encode Sans for every label; sentence case for all else.
- Tables that become lists of records when their card is too narrow.

## Colors

Purple and gold from the UW brand, used as surfaces and text; teal used as a
line.

### Primary

- **Spirit Purple** (`primary`, upstream `purple-700`): headings, links, the
  figure in a stat, the filled button, the outline button's border and text, a
  ticked checkbox, the text cursor. At 50% opacity it is the focus ring.
- **Husky Purple** (`primary-hover` and `nav`, upstream `purple-900`): the
  sidebar, the signed-out field, the card that shows a new key, and the hover
  state of the filled button and of links.
- **Purple Wash** (`secondary`, upstream `purple-50`): the hover fill of ghost
  and inverse buttons, and the count pill in a tab, with Husky Purple text.

### Secondary

- **Accent Teal** (`signature`, upstream `teal-500`): the 2px line under the
  current sidebar item and the open tab, and the loading line under the top bar.
  On the dark purples it is also the text of a code block and the focus ring of
  sidebar links.

### Tertiary

- **Light Gold** (`nav-foreground`, upstream `gold-200`): sidebar item text at
  rest; it turns white on hover and on the current item.
- **Husky Gold** (`nav-muted`, upstream `gold-500`): the sidebar's group labels.
- **Warm Ground** (`page`, upstream `gold-50`): the page behind every card.

### Neutral

- **White** (`card`): cards, the top bar, inputs, dialogs, notices.
- **Ink** (`foreground`, upstream `neutral-900`): body text and table cells.
- **Secondary Ink** (`muted-foreground`, upstream `neutral-600`): ledes,
  descriptions, hints, table headings, tag text, tabs at rest.
- **Cool Surface** (`muted`, upstream `neutral-50`): a pending invitation's row,
  the block of terms text, and at 50% a table row under the pointer.
- **Hairline** (`border`, upstream `neutral-200`): every border and divider,
  including input borders.
- **Deep Purple** (`terminal`, upstream `purple-950`): the ground of a code
  block.
- **Error Red** (`destructive`) and **Error Wash** (`bad-surface`): the
  destructive button, a refused form's message, and the tag for a denied or
  refused entry.
- **Success Green** (`good`): the icon of a notice that an action worked. It has
  no other use.

The knowledge graph alone uses six further upstream colours, one per concept
type (`purple-700`, `gold-700`, `teal-600`, `pink-600`, `green-600`,
`neutral-600`), and marks the selected concept with a `teal-600` outline.

### Named Rules

**The Teal Line Rule.** On a light surface, teal appears only as the 2px line
that says where you are or that a page is on its way. It is never a fill, a text
colour or a button there. Teal on white is under 2:1, so the line never carries
a state alone: the current tab also changes from Secondary Ink to Spirit Purple
and carries `aria-current`.

**The Borrowed Palette Rule.** A colour is used through a theme name (`primary`,
`nav`, `page`, `signature`), and every theme name points at an upstream token. A
hex value written into a component is a defect.

## Typography

- **Display Font:** Encode Sans Variable (with -apple-system, Segoe UI, Roboto)
- **Body Font:** Open Sans Variable (with the same system fallbacks)
- **Label Font:** Encode Sans Variable at 75% width, standing in for upstream's
  Encode Sans Compressed
- **Mono Font:** JetBrains Mono Variable (with Fira Code, Source Code Pro,
  Consolas)

**Character:** The UW pairing, unaltered: a sturdy geometric sans for names and
figures, a neutral humanist sans for reading, and the same display face squeezed
narrow and set in capitals for anything that labels something else. The fonts
are bundled with the console; nothing is fetched from another origin.

Sizes are upstream's fluid steps, which grow by about one pixel between a phone
and a wide screen. Line heights and letter spacing are upstream's too.

### Hierarchy

- **Display** (800, 24 to 32px, line height 1, tracking -0.015em, tabular
  figures): the figure in a stat. Spirit Purple. Nowhere else.
- **Headline** (700, 24 to 32px, line height 1.15, tracking -0.015em): the one
  page title per screen, Spirit Purple, with an optional status tag beside it.
- **Title** (600, 18 to 20px, line height 1.3): a card's heading. A sub-heading
  inside a card is the same face at 16 to 17px above a hairline.
- **Body** (400, 16 to 17px, line height 1.625): ledes and rendered knowledge
  text, held to 75ch. Inside cards and tables the text is 14 to 15px.
- **Label** (600, 12 to 13px, tracking 0.05em, uppercase, 75% width): table
  headings, stat labels, tag text. The same style at 14 to 15px labels form
  fields, tabs and buttons (buttons at 0.025em); sidebar group labels and tags
  open the tracking to 0.1em.
- **Mono** (500, 14 to 15px): anything a person types or copies exactly: model
  names, key hints, action names, client ids, addresses. Weight 400 inside a
  code block.

### Named Rules

**The Label Rule.** Uppercase compressed type labels a control or a piece of
data that sits right next to it: a column, a field, a figure, a tab, a button.
It is never set above a heading as a category line.

**The Typed Things Rule.** If a client or a person has to type it exactly, it is
in mono. If not, it is not.

## Layout

The shell is fixed. From 1024px up, a 256px sidebar is pinned to the left edge
at full height and the page is offset by the same amount. A 56px white top bar
sticks to the top with a hairline beneath it: the breadcrumb trail at the left,
the signed-in address and Sign out at the right. The page is a single column, at
most 1400px wide and centred, with 24px between its parts and padding of 16px on
a phone, 24px from 640px and 32px from 1024px.

A page reads in a fixed order: title and one-line lede; an optional plain note;
one strip of figures; on an organization or a team, a row of tabs; then cards.
Cards sit in a single column or in two equal columns from 1024px or 1280px,
always with a 24px gap and aligned to their tops. A list with a form that adds
to it uses the split: the list takes two parts and the form one part (never
under 320px), side by side once their container reaches 68rem, stacked before
that. Nothing that adds to a list is hidden behind a button.

Spacing is upstream's 4px scale. The steps in use are 6px (label to field), 8px
and 12px (inside rows and between small items), 16px (between fields), 20px
(between the parts of a card), 24px (card padding, gaps between cards) and 32px
(between tabs, desktop page padding).

Responsive behaviour is driven by the width of the container, not only of the
window:

- Under 1024px the sidebar is gone and a menu button in the top bar opens the
  same navigation as a full-screen sheet.
- Under 640px the trail shows only the current page; under 768px the signed-in
  address leaves the top bar and appears at the foot of the menu sheet.
- The stat strip is two columns, with an odd last figure spanning both, and
  becomes a single row from 1280px.
- A table whose card is narrower than it needs (30rem, 40rem or 54rem, chosen
  per table) becomes a list of records. See Tables.
- Fields that sit side by side stack when their card is under 32rem.
- A dialog's buttons stack, with the confirming button on top, under 640px.

Before sign-in there is no shell: one white card, at most 36rem wide, sits over
the lower edge of a Husky Purple field that covers the top 62% of the screen and
is cut along its bottom at upstream's 15 degree brand angle.

## Elevation & Depth

The system is nearly flat. Depth comes from three tones (Husky Purple sidebar,
Warm Ground page, white card) and from hairlines. Shadows are small and mark
only what floats above the page. Nothing gains a shadow on hover.

### Shadow Vocabulary

- **Resting card** (`box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.05)`): every card and
  the stat strip, always together with a 1px hairline border.
- **Floating**
  (`box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)`):
  a notice, and the signed-out card.
- **Dialog**
  (`box-shadow: 0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)`):
  a dialog, over a backdrop of black at 50%.
- **Teal glow** (`box-shadow: 0 0 20px rgba(42, 210, 201, 0.2)`, upstream
  `--shadow-glow-teal-md`): the card that shows a new key, and only that card.

The first three are the values the build produces from the framework's shadow
scale. They sit close to upstream's `--shadow-xs`, `--shadow-lg` and
`--shadow-xl` but are not those tokens.

Stacking is three levels: top bar (20), sidebar (30), notices (50). Dialogs and
the menu sheet use the browser's top layer.

### Named Rules

**The Border First Rule.** A card is drawn by its hairline; the shadow only
softens it. A surface that needs a larger shadow to be seen is floating, and
only notices, dialogs and the signed-out card float.

## Shapes

Three corner sizes, each with one job. Buttons are square (0), as the UW brand
requires. Cards, the stat strip, inputs, selects, text areas, sidebar rows, code
blocks, notices and inset rows are gently rounded (8px). Dialogs and tags are a
step rounder (12px). The count in a tab is a pill, and a checkbox has 4px
corners.

Borders are 1px Hairline everywhere, with two exceptions that are both 2px: a
button's border, which is transparent except on the outline button, and the teal
line. Dividers inside a card are the same hairline: under each table row, above
a sub-heading, between the cells of the stat strip.

The one non-rectangular shape is the 15 degree cut on the signed-out field.

## Components

Controls are plain and exact: square, labelled in capitals, and never larger
than the job. Every interactive element has a visible focus state, and every
transition is a colour change that reduced-motion settings switch off.

### Buttons

- **Shape:** square corners (0), a 2px border that is transparent unless stated,
  label style at 14 to 15px with 0.025em tracking, icons at 16px.
- **Sizes:** 40px tall with 20px side padding by default; 32px with 12px and 12
  to 13px text for actions inside a row or a card heading; 48px with 24px for
  the single action on a signed-out page.
- **Primary:** Spirit Purple fill, white text; Husky Purple on hover. One per
  form: the action that saves or sends.
- **Outline:** Spirit Purple border and text on no fill; fills Spirit Purple
  with white text on hover. For a secondary route out of a card, and for Cancel
  in a dialog.
- **Ghost:** Spirit Purple text on no fill; Purple Wash on hover. For actions on
  a table row (Remove, Rotate, Revoke), "more" links in a card heading, Sign
  out, and the menu button.
- **Destructive:** Error Red fill, white text, 90% on hover. For what cannot be
  undone, in the page and again as the confirming button in its dialog.
- **Inverse:** white fill, Spirit Purple text. Only on a dark purple surface,
  such as Copy inside a code block.
- **Focus / Disabled / Busy:** a 3px ring of Spirit Purple at 50%; 50% opacity
  and no pointer events when disabled; a button is disabled and marked busy
  while its own call is in flight.

### Tags

- **Style:** a hairline outline with no fill, Secondary Ink text in the label
  style at 12 to 13px with 0.1em tracking, 12px corners. It may wrap onto two
  lines in a tight column.
- **Bad variant:** Error Wash fill, Error Red text, a border of Error Red at
  30%. For a denied or refused entry.
- **State:** a tag appears only when something is out of the ordinary
  (`suspended`, `archived`, `denied`). The ordinary state has no tag.

### Cards / Containers

- **Corner Style:** 8px.
- **Background:** white on the Warm Ground page.
- **Shadow Strategy:** the resting card shadow with a hairline border. See
  Elevation & Depth.
- **Internal Padding:** 24px on all sides, 20px between the parts inside.
- **Heading:** a Title in Spirit Purple, an optional one-line description in
  Secondary Ink held to 75ch, and an optional small button at the top right.
- **Inverse card:** a card on Husky Purple with white text and the teal glow,
  holding one code block. It is used once, for a key that will not be shown
  again.
- **Notes:** a plain note under the page title (an archived team, an admin's
  limited view) is a white box with a hairline, 14 to 15px Secondary Ink text,
  and no icon.

### Stat strip

One strip per page, directly under the title. Its cells are white, 24px by 20px
padded, divided by hairlines inside a single 8px-cornered outline. Each cell is
the figure in Display, its label beneath in the label style, and an optional
line of detail in Secondary Ink ("2 invited or waiting", "team budget $200.00").
Three or four figures; two columns until 1280px, then one row. A figure is a
number the server sent or a count of what the page lists.

### Tables

- **Style:** no outer border and no zebra. Headings in the label style, 40px
  tall; cells at 14 to 15px with 8px padding; a hairline under every row; a row
  under the pointer takes Cool Surface at 50%.
- **Figures:** right-aligned with tabular digits, heading included.
- **Row actions:** small ghost buttons in a last, unlabelled column, right
  aligned.
- **Empty:** one sentence in Secondary Ink in place of the rows.
- **As records:** when its card is too narrow, each row becomes a record: the
  first cell in semibold on a line of its own, the other cells in a grid of
  columns at least 8rem wide, each under its column heading in the label style,
  and the actions last. A long log uses the dense form: first cell on its own
  line, the rest running on unlabelled, empty cells dropped.

### Inputs / Fields

- **Style:** 44px tall, white, 1px Hairline border, 8px corners, 12px side
  padding; 16px text on a phone and 14 to 15px from 768px. The select is the
  browser's own, with a 16px chevron at its right edge. A checkbox is 16px with
  4px corners and fills Spirit Purple when ticked.
- **Label:** above the field, tied to it, in the label style at 14 to 15px, 6px
  from the field. A hint, when there is one, sits under the field in Secondary
  Ink.
- **Focus:** the border turns Spirit Purple and gains a 3px ring of Spirit
  Purple at 50%.
- **Error / Disabled:** the server decides what is valid. Its reason appears
  under the fields in Error Red inside a hairline box, and what was typed stays.
  A disabled field is at 50% opacity.

### Navigation

- **Sidebar:** Husky Purple, 256px. The wordmark at the top is "LLMoxie" in bold
  white Encode Sans followed by "console" in regular Light Gold. Items are 40px
  rows with 8px corners, a 16px line icon and a label in the label face at 16 to
  17px, semibold, sentence case, 0.025em tracking, Light Gold. Groups ("Your
  organizations", "Your teams", "Administration") are headed in Husky Gold in
  the label style with 0.1em tracking, 24px apart. A child item has no icon and
  is indented to align with its parent's text.
- **States:** hover is white at 10% with white text. The current item keeps that
  fill and white text and gains the teal line under its words. Focus is a 2px
  teal ring.
- **Top bar:** white, 56px, hairline below. The trail is 14 to 15px: earlier
  steps as Secondary Ink links separated by 16px chevrons, the current page in
  semibold Ink. A page with nothing above it shows no trail.
- **Tabs:** a row under the stat strip, 32px apart, in the label style at 14 to
  15px, over a hairline. At rest Secondary Ink; on hover and focus Spirit
  Purple; the open tab is Spirit Purple with the teal line. A count sits in a
  Purple Wash pill. The open tab is in the address, so it survives a reload. The
  row scrolls sideways when it does not fit.
- **Phone:** the sidebar's contents open as a full-screen sheet in the darkest
  purple (upstream `purple-950`, as the SSEC system asks of a phone menu) on the
  native dialog element, with the wordmark and a close button at the top and the
  signed-in address at the foot. Following a link closes it.

### The teal line

The signature of the system as the console uses it: a 2px Accent Teal line in
three places. Under the words of the current sidebar item; under the open tab;
and, while a page's data is loading, as a segment two fifths of the bar's width
sweeping left to right along the bottom edge of the top bar every 1.1 seconds.
There it runs along a 2px Husky Purple track, because teal alone is too faint on
white to be seen. With reduced motion the segment stays still at the track's
left end.

### Code block

For a key, an address, anything to be copied exactly: a Deep Purple block with
8px corners and 16px by 12px padding, teal mono text that breaks anywhere, and
an optional small inverse Copy button at the right that reads "Copied" once
used. Inline names in running text and tables are mono in the surrounding
colour, with no background.

### Dialogs

The browser's own `<dialog>`: white, at most 32rem wide and 16px from the
screen's edges, 12px corners, a hairline border, the dialog shadow, 24px
padding, over a black 50% backdrop. Title at 20 to 24px, description in
Secondary Ink, buttons at the bottom right with Cancel as an outline button. A
question before something irreversible cannot be dismissed by clicking outside.
Removing a team or an organization requires its name to be typed before the
destructive button works.

### Notices

The answer to an action appears at the bottom right: a white box 24rem wide with
8px corners, a hairline, the floating shadow, a 16px icon (Success Green check
or Error Red alert), the message, and a dismiss button. A failure has a border
of Error Red at 40% and is announced as an alert.

## Do's and Don'ts

### Do:

- **Do** take every colour, size, line height and tracking value from a theme
  name that points at the pinned upstream token file.
- **Do** build a new screen from the existing parts in the existing order: page
  title, stat strip, optional tabs, cards.
- **Do** mark the current place with the 2px teal line together with a change of
  text colour and `aria-current`.
- **Do** keep buttons square and everything else that has a surface at 8px, with
  12px for dialogs and tags.
- **Do** set labels of columns, fields, figures, tabs and buttons in the
  uppercase compressed style, and everything else in sentence case.
- **Do** put the form that adds to a list in its own card beside that list, and
  let the split stack it underneath when the container is under 68rem.
- **Do** give each table the container width under which it becomes records, so
  a row's actions never leave the screen.
- **Do** say what an irreversible action does in the card that holds its button,
  and ask again in a dialog.
- **Do** build an overlay on the native `<dialog>` element and lock the page
  behind it with a class.

### Don't:

- **Don't** edit `ssec-tokens.css` or write a hex value into a component.
- **Don't** add dark-theme styles. The console is light only, by decision.
- **Don't** draw a chart, a sparkline, a trend arrow or a placeholder for one. A
  figure on screen is one the server sent.
- **Don't** use teal as a fill, a text colour or a button on a light surface, or
  as the only sign of a state.
- **Don't** use a component that inserts a style element or an inline style at
  run time. The content security policy refuses it, which rules out the Radix
  dialog, select and sheet.
- **Don't** round a button, and don't add a shadow to a button or to a hover
  state.
- **Don't** set the uppercase label style above a heading as a category line.
- **Don't** tag the ordinary state. `active` shows nothing.
- **Don't** turn the stat strip into separate tiles, or add a second strip to a
  page.
