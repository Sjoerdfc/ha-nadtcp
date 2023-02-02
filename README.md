As of januari 2023, this version is working for my NAD C338 amplifier.

# nadtcp

configuration.yaml
```yaml
media_player:
  - platform: nadtcp2
    name: nad-amp
    max_volume: -20
    min_volume: -70
    volume_step: 2
    host: 192.168.1.112
```
