# Coordinate Lock Concurrent Auto Hit Design

## Goal

Allow Coordinate Lock Auto Hit to keep sending left clicks while `Look at target` is still turning the camera toward an eligible entity. Camera alignment is not an Auto Hit prerequisite.

## Existing Problem

Coordinate movement, camera tracking, and Auto Hit currently request the same non-blocking movement input session. A smooth camera correction holds that session for the full correction, while Auto Hit abandons its click immediately when the session is unavailable. Repeated camera corrections can therefore suppress clicks until the camera reaches the target and stops issuing mouse movement.

## Input Coordination

`KeyboardInputCoordinator` will provide a dedicated click session. A click session may run concurrently with an active movement/camera session because Minecraft accepts a left click while movement keys are held or relative mouse movement is being sent.

Click sessions remain mutually exclusive with chat input. The coordinator will make the decision under its state lock and keep that lock across the short click operation so a chat session cannot start between the eligibility check and click. Once a chat session is pending or active, new click sessions are denied. Existing chat priority over movement remains unchanged.

Auto Hit will use this click session instead of the movement session. Movement and camera code will continue using the existing movement session without behavioral changes.

## Auto Hit Behavior

When Auto Hit is enabled, the worker will continue attempting clicks at the configured randomized interval even if `Look at target` is still correcting yaw or pitch and even while Coordinate Lock is moving the player back toward the saved coordinate.

All existing click eligibility and safety rules remain in force:

- the program, Coordinate Lock, active saved coordinate, and Auto Hit are enabled;
- the player is inside the saved coordinate's Active area;
- Minecraft is the foreground window;
- no inventory or container is open;
- an eligible entity is within the existing five-block Auto Hit radius;
- the saved Players/Mobs selection and optional Target Name filter match that entity; and
- no chat session is pending or active.

Camera target selection remains independent: `Look at target` may track an eligible entity anywhere inside the larger Active area, but Auto Hit clicks only while a matching entity is within five blocks. If no eligible Auto Hit target is present, no click is sent.

## Failure Handling

The worker will continue to fail closed when foreground, container, entity, or input-coordination checks fail. Endpoint errors retain the existing deduplicated Activity logging. A denied click session is treated as a skipped attempt and retried on the normal polling interval; it does not interrupt camera tracking or movement.

## Testing

Automated tests will verify that:

- a click session is allowed while a movement/camera session is active;
- a click session is denied while chat is pending or active;
- Auto Hit clicks while a camera movement session is active;
- existing foreground, container, five-block distance, entity-type, and Target Name gates remain intact; and
- movement and camera input continue to defer to chat.

Focused coordinator and Coordinate Lock tests will run first, followed by the complete pytest suite and a package syntax check.
