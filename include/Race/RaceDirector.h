#pragma once

// DashDecomp — Race::RaceDirector
// Status: NODECOMPILED 🔴

namespace Race {

/**
 * RaceDirector — Main controller for the race simulation loop.
 * Manages initialization, per-frame update, and teardown of a race session.
 *
 * Known from: CTGP-7 source + PabloMK7 symbol maps
 */
class RaceDirector {
public:
    // STATUS: NODECOMPILED — implement in src/Race/RaceDirector.cpp
    void init();
    void calc();
    void exit();

private:
    // TODO: populate struct members via Ghidra analysis
    // u32  mState;
    // u32  mLapCount;
    // ...
};

} // namespace Race
