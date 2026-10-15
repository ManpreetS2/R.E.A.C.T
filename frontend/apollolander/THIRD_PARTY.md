ApolloLander upstream
=====================

Source: https://github.com/sebleedelisle/apollolander
Commit: 0da09dccbadf0d6ee6efcce1f72e9ae206d341d2 (2017-06-22, "changed fonts to Hershey")
Website: http://moonlander.seb.ly/

The `upstream/` directory is the unchanged game. Experiment code lives in
`experiment/` and does not replace these files.

License
-------

Game code: MIT. Copyright (c) 2017 Seb Lee-Delisle. See `upstream/LICENSE`.

Third-party pieces shipped inside that repository:

| Path | What it is | License note |
| --- | --- | --- |
| `upstream/perlin.js` | Simplex/Perlin noise by Stefan Gustavson, optimised by Peter Eastman, JS port by Joseph Gentle | Public domain (header in the file). Attribution retained. |
| `upstream/libs/audio.js`, `jsfx.js`, `jsfxlib.js` | Procedural sound (jsfx / jsfxr style) | No license header in the upstream files. Used only by the original game's audio. The experiment simulator does not load them. |
| `upstream/libs/rAF.js` | requestAnimationFrame polyfill by Erik Möller, Paul Irish, and Tino Zijdel | Comment credits the authors. Original game only. |
| `upstream/libs/Vector2.js`, `KeyTracker.js`, `TouchController.js` | Game utilities in the same repository | Covered by the MIT license above. No separate notice in the files. |
| `upstream/fonts/avhersheysimplexmedium-webfont.woff` and `.woff2` | Hershey Simplex webfont | Hershey vector fonts are U.S. government work and are public domain. The webfont packaging has no extra license file in the repository. Kept only to preserve the original on-screen type. |

Do not strip `upstream/LICENSE` when redistributing the game.
