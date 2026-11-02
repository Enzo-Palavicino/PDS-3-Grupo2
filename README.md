# PDS-3-Grupo2

Plataforma de salud para los niños y niñas residentes del Hogar Misión de María.
Proyecto 3 de ICC4201 Proyecto de Desarrollo de Software, Universidad de los Andes.

Los profesionales podrán registrar atenciones desde la web y también por Telegram y WhatsApp,
enviando texto o audio. La IA transcribe los audios y extrae los campos del "Registro de Atención
y Control de Salud", que quedan como borradores para que un profesional los revise.

## Reglas del repositorio

El repositorio es público:

- nunca subas tokens, claves ni el archivo `.env`;
- usa solo datos ficticios, nunca datos reales de los niños, del Hogar ni de sus funcionarios;
- los logs registran solo ids y estados, nunca el contenido de los mensajes ni datos clínicos.

## Requisitos

- Python 3.11 o superior.

## Instalación local

Se hace una sola vez, desde la carpeta del repositorio.

1. Crea el entorno virtual:

   ```bash
   python -m venv .venv
   ```

   Es una carpeta `.venv` con un Python propio del proyecto. Ahí se instalan sus librerías sin
   tocar el Python global del computador. Git la ignora.

2. Actívalo, para que `python` y `pip` en esa terminal usen el entorno:

   - Windows (PowerShell): `.venv\Scripts\Activate.ps1`
   - macOS o Linux: `source .venv/bin/activate`

   Si PowerShell responde que "la ejecución de scripts está deshabilitada en este sistema",
   revisa la sección [Error de PowerShell al activar el entorno](#error-de-powershell-al-activar-el-entorno).

3. Instala las librerías:

   ```bash
   pip install -r requirements-dev.txt
   ```

   Se instalan las versiones exactas del proyecto, las mismas que usan el resto del grupo y
   GitHub Actions.

4. Crea tu configuración local (el comando funciona en PowerShell y en bash):

   ```bash
   cp .env.example .env
   ```

   En `.env` van los tokens y las claves. Nunca se sube al repositorio.

### Error de PowerShell al activar el entorno

Windows bloquea por defecto la ejecución de scripts de PowerShell, y `Activate.ps1` es un script.
Para permitir los scripts locales solo en tu usuario (no requiere administrador):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Los scripts descargados de internet siguen necesitando firma. Si prefieres no cambiar nada de
forma permanente:

- solo para la ventana actual: `Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process`;
- sin activar el entorno: usa su Python directamente, por ejemplo `.venv\Scripts\python -m pytest`.

## Ejecutar la aplicación

```bash
uvicorn app.main:app --reload
```

uvicorn es el servidor que ejecuta la aplicación: abre `http://localhost:8000` y le pasa cada
petición a FastAPI. `--reload` la reinicia cada vez que cambia el código. Para comprobar que
funciona, abre <http://localhost:8000/health>.

## Tests y lint

```bash
pytest
ruff check .
```

`pytest` corre los tests automáticos, y `ruff` revisa errores comunes (por ejemplo, imports o
variables sin usar) y el orden de los imports. GitHub Actions corre ambos en cada push: el
resultado se ve en la pestaña Actions y en el PR. Los tests no usan servicios externos.

## Estructura

```
app/
  main.py     crea la aplicación y define GET /health
  config.py   configuración leída desde variables de entorno o .env
  logs.py     configuración de los logs
tests/        tests automáticos
```
