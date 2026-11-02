# Pull request preparado para Almamu/linux-wallpaperengine (SIN PUBLICAR)

- Rama local: `puppet-mdl-skinning` en `~/.cache/ripowall-motor/src` (un commit sobre `38a5d60c`; es el mismo
  contenido que `engine/patches/0001-puppet-warp.patch`).
- Para publicarlo hace falta un fork en la cuenta de GitHub del usuario. Las capturas de `engine/capturas/` se
  adjuntan arrastrándolas al cuerpo del PR en la web.
- Pasos, solo con la aprobación del usuario:

```bash
gh repo fork Almamu/linux-wallpaperengine --clone=false
cd ~/.cache/ripowall-motor/src
git remote add fork https://github.com/Joaco2382/linux-wallpaperengine.git
git push fork puppet-mdl-skinning
gh pr create -R Almamu/linux-wallpaperengine --head Joaco2382:puppet-mdl-skinning --base main \
  --title "feat: puppet warp for every MDLV version, with skeleton and animations" --body-file <cuerpo de abajo>
```

---

## Título

feat: puppet warp for every MDLV version, with skeleton and animations

## Cuerpo

> AI-assisted contribution (Claude Code), reviewed and tested as described below. Please review it as such.

### Problem

Puppet warp image layers only loaded for `MDLV0021`/`MDLV0023`, and even then the mesh was drawn as stored. Many
puppets store their pieces (head, eyes, arms, props) spread over a sprite sheet and rely on the skeleton to put
them in place, so those pieces floated around (#626, #669, #239). Every other version was rejected with
`Unsupported puppet model header`.

A second problem made whole characters disappear. The mesh was drawn in the first pass, into the layer's
framebuffer, and the effects then ran on the posed result. Effects that make the whole layer opaque, such as
`tint` with `BLENDMODE 0` (used by "character outline" layers), turned the layer's whole rectangle into a
solid block that covered everything drawn before it. In workshop 2791601501 (SPY x FAMILY), Yor's outline layer
hides Anya completely. Effect masks, which are painted on the flat image, also ended up misaligned with the
posed pieces.

### Changes

- **`PuppetParser`** (new) reads the `.mdl` sections in order instead of using a fixed layout per version:
  - The vertex size comes from the vertex format descriptor right after the header: 52 bytes for `0x01800009`
    (MDLV0013/0014) and 80 for `0x0180000F` (adds normal + tangent).
  - The mesh is located by validating the whole vertex + index block: it must end right at `MDLS` and every
    index must be in range. Newer versions add fields before the vertices, so there's no fixed offset.
  - `MDLS` skeleton: per bone, the parent and a bind transform relative to the parent. The section's end offset
    skips version specific trailing data.
  - `MDLA` animations: id, play mode, fps, length and one track of keyframes per bone (position, angles, scale).
    Each animation is found by validating its layout, which skips the padding and event lists that differ
    between versions. The scene's animation layer ids break the one ambiguous case: an empty string before the
    name vs. the regular layout read one byte off.
  - If the skeleton or animations can't be read, the mesh is kept in its bind pose. If the mesh can't be read,
    the layer is drawn as the plain image instead of disappearing.
- **`PuppetPose`** (new) applies the object's `animationlayers` (`loop`, `mirror`, `single`, `rate`, `blend`) to
  the skeleton and skins the mesh on the CPU every frame (4 influences per vertex). Keyframe angles are authored
  with y pointing down, so rotations around x and z are flipped for the y-up mesh. This was verified against
  the motion in the preview of 2327607728.
- **`CImage`**: like Wallpaper Engine, effects run on the flat image and the posed mesh is only used for the final
  draw into the scene, in scene space, sampling the effects' output with the mesh's texture coordinates. When
  the layer has no effects, it samples the texture directly, accounting for padding. Face culling is disabled
  while drawing the mesh, because the y flip reverses the winding (#620).
- Catch2 tests (`Testing/Cases/PuppetParser.cpp`, 13 cases). They use synthetic files with the MDLV0013/0014
  layout and the newer one (80 byte vertices, extra header fields, padding and event lists between animations),
  plus play modes, rotation direction and blending from a rotated bind pose.

### Testing

Screenshots with `--screenshot` in a headless mutter (1280x720, 5 s), compared to each item's `preview.gif`:

| Workshop | MDLV | Before | After |
|---|---|---|---|
| 2791601501 SPY x FAMILY | 0014 (3 characters on sprite sheets) | Anya hidden, Loid and Yor without eyes, eyes/props floating | Matches the preview, animations play |
| 2452613331 Zero Two | 0013 | Hair tuft floating next to the head | In place |
| 2327607728 Ahsoka | 0013 | Arms static | Arms animate like the preview |

*(attach `engine/capturas/*.jpg` from RipoWall here)*

Regression: 20 scenes without puppets, captured twice with unpatched `38a5d60c` and once patched. For every scene,
the patched difference (RMSE) stays within the run to run difference of the unpatched engine, and static scenes
are pixel identical.

Not tested on real files: MDLV0017/0019/0021/0023 (I don't have those wallpapers). They're covered by the
synthetic tests of the newer layout. It would be great if someone could try 3113287126 (#669), 2844426226
(#626), 3796026374 (#626) and 3558034522 (#620). It may also help #702: the posed mesh is no longer clipped by
the layer's framebuffer, but that hasn't been verified.

### Not implemented

- Additive animation layers are blended like regular ones (the `additive` flag isn't parsed).
- Bone physics/cloth simulation (the per-bone simulation json) is ignored.

Related: #620, #626, #669, #239, #702 and the closed draft #625. #698 also disables culling for puppets.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

# Los otros arreglos (parches 0002–0009): PRs aparte, también sin publicar

Cada uno es independiente y conviene proponerlo por separado (un PR por arreglo), con su prueba Catch2:

| Parche | Repositorio | Commit local |
|---|---|---|
| 0002 uniform types | Almamu/linux-wallpaperengine | `fcef9585` en `~/.cache/ripowall-motor/src` |
| 0003 narrow fragment varyings | Almamu/linux-wallpaperengine | `698f2660` |
| 0004 HLSL vector truncation | Almamu/glslang-WallpaperEngine (el fork de glslang) | `5747ebe6` en `src/External/glslang-WallpaperEngine`, rama `hlsl-vector-truncation` |
| 0005 fragment varyings | Almamu/linux-wallpaperengine (necesita el 0004 para sus pruebas HlslShapes) | `7fcae697` |
| 0006 auto projection | Almamu/linux-wallpaperengine | `ba788ffd` |
| 0007 pointer at rest | Almamu/linux-wallpaperengine | `898b1ad0` |
| 0008 fill/fit side | Almamu/linux-wallpaperengine | `89c3d150` |
| 0009 unique framebuffers | Almamu/linux-wallpaperengine | `eb993a28` |

El mensaje de cada commit ya explica el problema, la causa, el arreglo y las escenas del Workshop que lo muestran.
