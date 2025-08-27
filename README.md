# Times of the Day

A Home Assistant helper integration that exposes binary sensors indicating whether the current time falls within a specified range. Each sensor is defined by two boundaries, **after** and **before**, which can be a clock time or sun event (sunrise/sunset) with optional offsets.

## Features
- Supports both YAML and GUI configuration
- Boundaries can use fixed times or sun events
- Offsets allow adjusting triggers relative to sunrise or sunset

## Development
This repository contains the core of the integration. To test changes in a Home Assistant environment, copy the `tod` directory to your `custom_components` folder in Home Assistant.

## License
MIT
