# VHF Driver Distribution

This project can produce two driver outputs:

- `Submission`: unsigned driver package plus a Partner Center submission CAB.
- `Test`: locally test-signed driver files for lab machines only.

Use `Submission` for real distribution. Do not ask end users to enable Windows test-signing mode.

## Build Submission Package

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\VhfDriver\build_driver.ps1 -SourceRoot "C:\QA Security Project" -SigningMode Submission
```

Output:

```text
Build\VhfDriver\VhfDriver.inf
Build\VhfDriver\VhfDriver.sys
Build\VhfDriver\VhfDriver.cat
Build\VhfDriver\VhfDriver.pdb
Build\DriverSubmission\RiceHarvesterVhfDriver_Submission.cab
```

Upload the CAB to Microsoft Partner Center / Hardware Dev Center for attestation signing. After Microsoft returns the signed package, replace the files under:

```text
Agent\VhfDriver
```

or the built Alpha output:

```text
C:\QA Security Project_Test_Alpha\Agent\VhfDriver
```

with the Microsoft-signed `VhfDriver.sys`, `VhfDriver.inf`, and `VhfDriver.cat`.

## Optional EV CAB Signing

If the organization has an EV code-signing certificate available in the local certificate store, the submission CAB can be signed during build:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\VhfDriver\build_driver.ps1 -SourceRoot "C:\QA Security Project" -SigningMode Submission -EvCertificateThumbprint "<EV_CERT_THUMBPRINT>"
```

## Test Build Only

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\VhfDriver\build_driver.ps1 -SourceRoot "C:\QA Security Project" -SigningMode Test
```

This creates a local test certificate and signs the package for development use only.
