# Version 1.20 aka 120
[See Release Notes](https://github.com/jostrm/azure-enterprise-scale-ml/releases/tag/release_120)

## main.bicep
- param aifactoryVersionMajor int = 1
- param aifactoryVersionMinor int = 23

## Azure Devops - variables.yaml
```yaml
- aifactory_version_major: "1" # Major version of AI Factory. Used to determine which bicep files to use. 1, 2, etc.
- aifactory_version_minor: "20" # # 2025-05-23: 120_LTS
```

## Github - .env
```bash
- AIFACTORY_VERSION_MAJOR="1"
- AIFACTORY_VERSION_MINOR="23" # 2025-05-23: 120_LTS
```
