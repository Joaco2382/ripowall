# Motor de escenas de RipoWall

RipoWall dibuja las escenas de Wallpaper Engine con
[linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine). Hasta que los arreglos lleguen a upstream,
RipoWall instala ese motor en un **commit fijo** (`motor.conf`) con los parches de `patches/` aplicados.

| Archivo | Para qué |
|---|---|
| `motor.conf` | Repositorio y commit fijo de upstream |
| `patches/` | Los arreglos, en orden (tabla de abajo) |
| `PKGBUILD` | Paquete `linux-wallpaperengine-ripowall` para Arch (reemplaza a `linux-wallpaperengine-git`) |
| `instalar-motor.sh` | Instala el motor: en Arch construye e instala el paquete; en otras distros compila en `~/.local` |
| `capturas/` | Antes y después del parche, comparado con la `preview.gif` de cada escena |
| `PR-upstream.md` | El pull request preparado para upstream (sin publicar) |

## Instalar

```bash
engine/instalar-motor.sh             # o la opción [4] de install.sh
engine/instalar-motor.sh --revisar   # qué motor hay instalado
```

En Arch, pacman pide confirmar el reemplazo de `linux-wallpaperengine-git`. En otras distros hacen falta las
dependencias de compilación de upstream (lista en su README) y el comando queda en `~/.local/bin`.

## Los parches

| Parche | Qué arregla | Escenas de este PC |
|---|---|---|
| `0001-puppet-warp` | Personajes «puppet»: malla de cualquier versión MDLV, esqueleto, animaciones y efectos sobre la imagen plana | 2791601501, 2452613331, 2327607728 |
| `0002-uniform-types` | Uniforms enviados con el tipo real del programa (el parser no evalúa `#if` y registraba el de una rama inactiva); un error de OpenGL pendiente ya no anula `--screenshot` | 2228173242 (negra) |
| `0003-narrow-fragment-varyings` | Varyings del fragment más angostas que la salida del vertex: se declaran con el tipo del vertex y una macro las recorta (regla de HLSL) | 2403480896 (gris) |
| `0004-glslang-hlsl-vector-truncation` | En el submódulo glslang: `vec3 + vec2` recorta el vector más largo, como HLSL (solo afecta código que GLSL rechaza) | 2405891694 |
| `0005-fragment-varyings` | Varyings del vertex que el fragment lee sin declarar; varyings que el fragment escribe; JSON de metadatos con números como `01` | 2169779628 (gris), 2405891694 |
| `0006-auto-projection` | Proyección `auto` medida desde 0 y con su tamaño declarado (escenas GIF) | 1309424009, 1477353862, 1671718580, 1341926663 |
| `0007-pointer-at-rest` | Sin mouse (`--disable-mouse`, como lanza RipoWall) el puntero queda al centro: el paralaje ya no corre la escena | 1982331270, 2069970082 |
| `0008-fill-fit-side` | `fill`/`fit` eligen el lado a recortar por la escala y no por píxeles truncados | 2069970082 |
| `0009-unique-framebuffers` | Buffers `unique` de los efectos resueltos por su nombre de escena (`_rt_FullCompoBuffer1_12_33`) | 5 escenas con ese aviso |

## Qué arregla el parche de los puppets

Los personajes animados con *puppet warp* guardan sus piezas (cabeza, ojos, brazos) repartidas en una hoja de
textura y es el esqueleto el que las pone en su lugar. El motor de upstream (38a5d60c) solo aceptaba MDLV0021 y
MDLV0023 y aun así dibujaba las piezas sin el esqueleto. Además, los efectos corrían sobre la malla ya dibujada,
así que un contorno con `tint` (que deja la capa opaca) tapaba todo lo que había detrás de su rectángulo. Así
desaparecía Anya en SPY x FAMILY.

- Lee el `.mdl` por secciones, de cualquier versión: el tamaño del vértice sale del descriptor de formato y la
  malla y las animaciones se ubican validando su estructura completa.
- Aplica el esqueleto y las capas de animación de la escena (`loop`, `mirror`, `single`, `rate`, `blend`) cada
  cuadro.
- Igual que Wallpaper Engine, los efectos trabajan sobre la imagen plana y la malla con la pose solo da forma al
  dibujo final.
- Sin culling en la malla y, si no se puede leer, respaldo a la imagen plana: el personaje siempre aparece.

## Pruebas

- Pruebas unitarias en el parche (`src/WallpaperEngine/Testing/Cases/PuppetParser.cpp`, 13 casos): archivos
  sintéticos con el formato de MDLV0013/0014 y de las versiones nuevas (vértices de 80 bytes, campos extra,
  relleno entre animaciones), modos de reproducción, sentido de giro y mezcla.
- Capturas con `scripts/capturar-escena.sh` (con `MOTOR=` apuntando al motor compilado):
  2791601501 (MDLV0014), 2327607728 y 2452613331 (MDLV0013), comparadas con su `preview.gif` en `capturas/`.
- Regresión: 20 escenas sin puppets, capturadas dos veces con el motor original y una con el parchado. En todas,
  la diferencia con el parche quedó dentro de la que hay entre dos corridas del motor original.
- `tests/test_motor.py` y el CI comprueban que el paquete, el instalador y los parches coinciden y que los parches
  se aplican sobre el commit fijo.

## Prueba completa (2026-11-01): las 204 escenas de este PC

Tres corridas completas (motor original dos veces y motor parchado una vez) más una con `--scaling fill`,
revisadas a ojo contra la preview de cada escena y comparadas numéricamente contra el ruido entre corridas.

| Resultado | Escenas |
|---|---|
| Se ven bien con el parche (como las lanza hoy la extensión) | 174 (85 %) |
| … de ellas, arregladas por el parche (puppets) | 3 |
| Se arreglan además con `--scaling fill` (la escena no cubre la pantalla y los bordes se estiran) | 16 → 190 (93 %) |
| Tamaño o encuadre que esa opción no arregla (3 `gifscene`, proyección automática o cámara corrida) | 6 |
| Efectos que fallan (`_rt_FullCompoBuffer` sin resolver, tinte faltante, capa de más) | 4 |
| No dibujan (shaders que no compilan; efecto `clouds` con perspectiva en cero) | 4 |

- Regresión: con el parche, 192 de 204 quedan dentro del ruido. Las otras 12 son las 2 puppets que cambian a
  propósito y 10 que solo cambian por el momento de la animación (revisadas a ojo). Ninguna empeora.
- Logs: el parche no agrega avisos y elimina los 5 de «Unsupported puppet model header».
- `--scaling fill` no empeora ninguna de las 204; la extensión todavía no lo pasa.

## Resultado final (2026-11-02): 200 de 204

Con los 9 parches y `--scaling fill` (como lanza la extensión desde el PR #3), capturadas las 204 y comparadas
contra el motor de los puppets (también con `fill`) y contra el ruido entre dos corridas del original:

- **200 de 204 (98 %)** se ven como su preview. Las 10 que se arreglaron de las 14 pendientes coinciden con su
  preview. 2296491111 no estaba rota: la silueta con el sable rojo es parte de la ilustración, fuera del recorte
  de la preview.
- **Ninguna empeora:** 142 quedan dentro del ruido; de las 62 restantes, 9 son las arregladas, 2 son puppets y
  51 solo cambian por el paralaje (que ya no arranca desde una esquina) o la animación, revisadas a ojo.
- **Quedan 4**, con su causa acotada:
  - 2405891694 (Matrix): sus shaders ya compilan, pero la lluvia de letras es un sistema de partículas con
    partículas hijas (`children`, `eventfollow`), que el motor lee y nunca dibuja. Falta implementarlo
    (estimado: 2–4 días).
  - 1590620004 (cielo gris) y 2640039186 (velo): el efecto `motionblur` acumula cuadros en un buffer que no
    llega a converger. Las texturas y las pasadas (acumular → copiar → combinar) enlazan los buffers correctos
    y el resultado no cambia entre 10 y 400 cuadros; falta encontrar por qué el buffer no conserva lo copiado
    (estimado: 0,5–1 día).
  - 1192622070 (falta el tinte rojo): la niebla roja es un sistema de partículas (`fog2`, escala 5,
    `overbright` 5, `depthtest` activo) que no se dibuja ni sola; no es el culling (estimado: 1 día).
- Menor: 1365112016 deja una franja gris finita a los costados, igual antes y después de los parches.

## Actualizar el motor

1. Cambiar `MOTOR_COMMIT` en `motor.conf` y `_commit`/`pkgver` en `PKGBUILD`.
2. Rehacer los parches sobre el commit nuevo (o quitar los que ya estén en upstream) y actualizar `sha512sums`.
   El 0004 cambia el submódulo de glslang: se genera con `git format-patch` dentro del submódulo y el prefijo
   `src/External/glslang-WallpaperEngine/`.
3. `python3 -m unittest discover -s tests` y capturar de nuevo las escenas de prueba.
