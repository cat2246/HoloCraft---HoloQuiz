# Player Horizontal Centering Design

## Goal

Center the complete Player information area horizontally at every supported window width while keeping it aligned to the top of the Player tab.

## Layout

The full-width Player toolbar remains unchanged. The body will use three grid columns: flexible left and right spacer columns with equal weight, and a non-expanding middle column containing the existing Player overview, Vitals, and Inventory widgets. The middle content wrapper stays anchored north, so additional vertical space remains below it.

The internal relationship between the profile panel and the Vitals/Inventory column remains unchanged. No widget sizes, inventory behavior, data loading, or tooltip behavior will change.

## Testing

A display-free layout test will verify that the body gives equal expansion weight to both side columns, places the content wrapper in the middle column, and uses north alignment. The focused Player view tests and full project test suite will be run after implementation.
