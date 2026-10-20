# single-file-cube-solve Specification

## Purpose
TBD - created by archiving change add-single-file-cube-solve. Update Purpose after archive.
## Requirements
### Requirement: Standalone fixed-orientation cube presentation

The artifact SHALL be a single offline-capable HTML file with embedded Three.js and a 1080×1080 render buffer. Its 3×3 cube SHALL use white up, yellow down, green front, blue back, red right and orange left. The camera and whole-cube orientation SHALL remain fixed while only face layers turn.

#### Scenario: Open the artifact

- **WHEN** the user opens the HTML directly or through a static HTTP server
- **THEN** the square scene renders without external resource requests and scales proportionally to fit the viewport
- **AND** only WCA face moves may change the cube state

### Requirement: Verified independent solution of the exact scramble

The artifact SHALL apply `D2 R' F U2 B' L2 D' R2 U F2 L' B2 U' R D2 F' L U2 B R'` using WCA notation to a solved cube, then solve the resulting state with an independently searched face-turn sequence rather than replaying the inverse scramble. It SHALL validate all 54 stickers against their original standard face colors before reporting success.

#### Scenario: Playback reaches the last move

- **WHEN** the independently computed solution is completely applied
- **THEN** every face has its original standard color and the rendered cubies agree with the logical sticker state
- **AND** the application reports success only after checking the actual state

### Requirement: Exact move timeline and completion timer

Each face move, including half turns, SHALL last 350 milliseconds with 50 milliseconds between successive moves. The display SHALL show elapsed solve time, current WCA move and completed move count. The timer SHALL stop at the end of the first move that actually solves the cube and SHALL exclude a trailing pause. Explicit user pause SHALL freeze the animation and timer; replay SHALL reset to the exact scrambled state.

#### Scenario: Uninterrupted playback

- **WHEN** the user starts or automatically watches the solve
- **THEN** move n begins at n×400 milliseconds and finishes at n×400+350 milliseconds for zero-based n
- **AND** the timer freezes at the actual solving boundary and remains unchanged afterward

#### Scenario: Pause and replay

- **WHEN** the user pauses, resumes or replays
- **THEN** pause preserves progress without adding paused time, and replay restores the exact initial scrambled state and zero completed moves

