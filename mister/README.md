# MiSTer core source

This folder vendors the emu-coop MiSTer NES core fork used by the beta4 POC.

- Quartus project: `mister/cores/NES_emu-coop/NES.qpf`
- Expected Quartus output: `mister/cores/NES_emu-coop/output_files/NES.rbf`
- Bridge payload copy: `bridge/bridge_core/mister_payload/NES_emu-coop.rbf`
- MiSTer deploy target: `/media/fat/_Console/NES_emu-coop.rbf`

Build from the repo root after installing Intel Quartus Prime Lite 17.0 with
Cyclone V support:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-mister-core.ps1
```

If Quartus is not on `PATH`, pass the install bin directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\build-mister-core.ps1 -QuartusBin C:\intelFPGA_lite\17.0\quartus\bin64
```

The wrapper runs `quartus_sh --flow compile NES` and then copies the generated
`.rbf` into the bridge payload using the non-stock `NES_emu-coop.rbf` name.
