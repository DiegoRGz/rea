# 🌐 Panorama 360°

Generador **local** de panorámicas 360° con IA, listas para subir a Facebook como foto 360.
Funciona en tu laptop, sin pagar ni subir nada a internet (solo descarga los modelos la primera vez).

- **Elige entre varios modelos** (fotorrealista, cinematográfico, artístico rápido, anime…) y genera
  **muestras** de cada uno para comparar la calidad antes de usarlo. Puedes añadir tus propios modelos
  SDXL (Hugging Face o archivos `.safetensors` de Civitai).
- **Lotes con cola**: indica cuántas panorámicas quieres y se añaden a la cola. Puedes seguir
  añadiendo lotes mientras se generan, pausar, cancelar o reintentar. La cola **se guarda**: si cierras
  la app, al volver continúa donde se quedó.
- **Imagen de referencia** con tres modos:
  - *Inspiración*: copia estilo, colores y ambiente de cualquier imagen (IP-Adapter).
  - *Variación*: parte de una panorámica 2:1 que ya tengas y crea versiones con la misma composición.
  - *Extender foto a 360°*: pones una foto normal al frente y la IA completa el resto de la esfera.
- **Sin costuras ni artefactos típicos**: el borde izquierdo y el derecho encajan perfectamente,
  el cenit y el nadir se limpian (sin "remolino") y el detalle se añade por mosaicos sin dejar bordes.
- **Se adapta a tu equipo**: detecta tu GPU y elige un perfil (8 GB → perfil *Media*).
- **Exporta JPEG con metadatos 360° (GPano)** para que Facebook lo muestre automáticamente como foto 360,
  y trae un visor 360° integrado para revisar el resultado antes de publicarlo.

## Requisitos

| | Mínimo | Recomendado |
|---|---|---|
| GPU | NVIDIA 6 GB (o Mac Apple Silicon) | NVIDIA 8 GB o más |
| RAM | 16 GB | 32 GB |
| Disco | ~15 GB libres | ~40 GB si pruebas varios modelos |
| Software | Python 3.11 o 3.12, driver NVIDIA actualizado | |

Sin GPU también funciona, pero cada panorámica puede tardar mucho.

## Instalación

**Windows: instalador `.exe` (recomendado)**

1. Descarga **`Panorama360-Setup.exe`** (ver abajo de dónde sale) y ejecútalo. No pide permisos de
   administrador; crea accesos directos en el escritorio y en el menú Inicio.
2. Abre **Panorama 360**. La primera vez muestra qué va a instalar (Python y PyTorch para tu GPU,
   ~6 GB) y espera a que pulses *Instalar ahora*; verás el progreso animado. Después la app abre en
   su propia ventana en segundos.
3. Tus panorámicas quedan en `Imágenes\Panorama360\salidas`. Al desinstalar se borra el motor
   (`%LOCALAPPDATA%\Panorama360`) pero se conservan tus panorámicas.

El instalador lo compila GitHub Actions en Windows (`.github/workflows/panorama360-windows.yml`)
en cada cambio de `panorama360/`: en la ejecución, sección *Artifacts* → **Panorama360-Setup**.
También puedes compilarlo tú en Windows con `.\desktop\build_windows.ps1`.
Como no está firmado digitalmente, Windows SmartScreen puede avisar: *Más información →
Ejecutar de todas formas*.

**Windows: scripts `.bat` (alternativa sin instalador)**

1. Instala [Python 3.12](https://www.python.org/downloads/) marcando *Add python.exe to PATH*.
2. Actualiza el driver de tu tarjeta NVIDIA.
3. Doble clic en **`instalar.bat`** (tarda unos minutos; descarga PyTorch con CUDA).
4. Doble clic en **`iniciar.bat`**. Se abre el navegador en <http://127.0.0.1:7860>.

**Linux / macOS**

```bash
./instalar.sh
./iniciar.sh
```

La **primera** vez que uses cada modelo se descarga (~7 GB) y queda guardado en la caché de
Hugging Face. El LoRA 360°, el adaptador de referencia (~3 GB) y el reescalador (~65 MB) también se
descargan solos la primera vez que hacen falta.

## Uso rápido

1. **Modelo**: elige uno. Pulsa *🧪 Generar muestra* para ver cómo trabaja en tu equipo; la muestra
   queda guardada junto al selector para la próxima vez. En *🧪 Comparar modelos* puedes generar la
   misma escena con la misma semilla en varios modelos a la vez y quedarte con el que más te guste.
2. **Escena**: describe lo que quieres ver a tu alrededor. **En inglés funciona mucho mejor**
   (por ejemplo: `snow covered baseball stadium with green seats, overcast winter sky`).
3. **Referencia** (opcional): sube una imagen y elige el modo. El control *Parecido a la referencia*
   ajusta cuánto se parece el resultado.
4. **Calidad y lote**: *Alta* añade una pasada de detalle (recomendado para publicar). Elige la
   resolución (4096 × 2048 es la recomendada para Facebook) y cuántas panorámicas quieres.
5. **➕ Añadir a la cola**. Los resultados aparecen a la derecha; haz clic en uno para abrirlo en el
   **visor 360°** o descargarlo.

Las panorámicas se guardan en `salidas/AAAA-MM-DD/` como JPEG con un `.json` al lado (prompt,
semilla, modelo y ajustes) para que puedas repetir cualquier resultado con la misma semilla.

### Subir a Facebook

Sube el `.jpg` tal cual como **foto** (no lo edites ni lo recortes antes, o se pierden los metadatos).
Facebook detecta la proyección equirectangular y lo muestra como foto 360° interactiva.

## Consejos de calidad

- Describe el **entorno completo** (suelo, horizonte, cielo), no un objeto: la panorámica te rodea.
- Si salen cosas raras arriba o abajo, deja activada *Limpiar cenit y nadir* y sube un poco el
  *Peso del LoRA 360°* en *Ajustes avanzados*.
- Para escenas reales (estadios, plazas, paisajes) usa **RealVisXL** o **Juggernaut**; para probar
  muchas ideas rápido usa **DreamShaper XL Turbo** (8 pasos) y luego repite la mejor semilla en otro
  modelo.
- Para mantener un estilo coherente en un lote, usa la misma imagen de referencia en modo
  *Inspiración* y la opción de semillas distintas.
- *Fuerza del detalle* alta (0.4–0.5) inventa más textura; baja (0.2) es más fiel a la base.

## Perfiles según tu equipo

| Perfil | Para | Qué hace |
|---|---|---|
| Alta | 12 GB+ VRAM | Todo en GPU, salida 6144 px |
| **Media** | **8–12 GB VRAM** | **Mueve a RAM lo que no se usa; salida 4096 px con detalle** |
| Baja | 5–8 GB VRAM | Mosaicos más pequeños |
| Mínima | <5 GB VRAM | Carga capa por capa (lento) |
| Mac | Apple Silicon | Metal (MPS) |
| CPU | Sin GPU | Funciona, pero muy lento |

Se elige solo al iniciar; puedes cambiarlo en *⚙️ Sistema*. Si ves "memoria de video insuficiente",
baja un perfil o la resolución.

## Cómo funciona (resumen técnico)

1. **Base** a 1536 × 768 con un modelo SDXL + LoRA 360° (proyección equirectangular). Todas las
   convoluciones del modelo y del VAE usan **relleno circular horizontal**, de modo que la red "ve"
   la imagen como un cilindro y el borde izquierdo continúa en el derecho.
2. **Reescalado** con Real-ESRGAN por mosaicos que dan la vuelta (sin costura).
3. **Pasada de detalle** (img2img por mosaicos tipo MultiDiffusion): cada paso de difusión predice el
   ruido por mosaicos solapados que también dan la vuelta y los mezcla con pesos suaves.
4. **Polos**: cerca del cenit y el nadir cada fila se suaviza progresivamente, porque en la
   proyección la fila superior entera es un solo punto.
5. **Exportación** JPEG con metadatos XMP GPano (los que usa Facebook para activar el visor 360).

Para *Extender foto*, la foto se proyecta en la esfera según su campo de visión y la difusión solo
inventa la parte que falta, mezclando en cada paso la parte conocida.

## Añadir modelos

En *🧩 Modelos* escribe un nombre y un ID de Hugging Face (p. ej. `RunDiffusion/Juggernaut-XL-v9`) o
la ruta a un `.safetensors` (Civitai). Debe ser de la familia **SDXL** (no SD 1.5 ni FLUX). También
puedes editar `config/models.json`.

## Problemas frecuentes

- **"Sin conexión para descargar el modelo"**: la primera vez que usas cada modelo necesitas internet.
- **"El modelo requiere aceptar su licencia"**: abre la página del modelo en Hugging Face, acepta la
  licencia e inicia sesión con `hf auth login` desde la carpeta de la app (`.venv\Scripts\hf auth login`).
- **El visor 360° no carga**: usa la librería Pannellum desde internet; el JPEG sigue estando en `salidas/`.
- **Muy lento**: comprueba en *⚙️ Sistema* que se detecta tu GPU NVIDIA. Si dice "Solo CPU", vuelve a
  ejecutar `instalar.bat` con el driver actualizado.

## Pruebas (desarrollo)

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

Las pruebas usan un modelo SDXL diminuto con pesos aleatorios: comprueban el flujo completo, la
continuidad 360°, la cola y la exportación, pero no la calidad visual de los modelos reales.

## Licencias

Este proyecto solo descarga y usa modelos de terceros; cada modelo, el LoRA 360°, IP-Adapter y
Real-ESRGAN tienen su propia licencia (consúltala en su página antes de un uso comercial).
