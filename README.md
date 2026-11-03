<!-- header:begin (generated from project metadata) -->
<h1 align="center">Example Integration</h1>

---

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&amp;repository=Home-Assistant-Integration-Template&amp;category=integration"><img src="https://img.shields.io/static/v1?label=HACS&amp;message=Add%20integration&amp;color=41BDF5&amp;logo=homeassistantcommunitystore&amp;logoColor=white&amp;style=for-the-badge" alt="HACS" height="28"></a>
  <a href="https://github.com/seb5594/Home-Assistant-Integration-Template/actions/workflows/compat.yml"><img src="https://img.shields.io/static/v1?label=home%20assistant&amp;message=%E2%89%A5%202024.4.0&amp;color=1877A5&amp;style=for-the-badge" alt="home assistant" height="28"></a>
  <a href="https://github.com/seb5594/Home-Assistant-Integration-Template/releases"><img src="https://img.shields.io/static/v1?label=version&amp;message=0.1.0&amp;color=1877A5&amp;style=for-the-badge" alt="version" height="28"></a><br>
  <a href="https://github.com/seb5594/Home-Assistant-Integration-Template/issues"><img src="https://img.shields.io/github/issues/seb5594/Home-Assistant-Integration-Template?label=issues&amp;style=flat" alt="issues" height="20"></a>
  <a href="https://github.com/seb5594/Home-Assistant-Integration-Template/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seb5594/Home-Assistant-Integration-Template/ci.yml?branch=main&amp;label=checks&amp;style=flat" alt="checks" height="20"></a>
  <a href="https://github.com/seb5594/Home-Assistant-Integration-Template#license"><img src="https://img.shields.io/github/license/seb5594/Home-Assistant-Integration-Template?label=license&amp;style=flat" alt="license" height="20"></a><br>
  <a href="https://paypal.me/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=PayPal&amp;color=0070BA&amp;logo=paypal&amp;logoColor=white&amp;style=for-the-badge" alt="PayPal" height="40"></a>
  <a href="https://buymeacoffee.com/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=Buy%20Me%20a%20Coffee&amp;color=FFDD00&amp;logo=buy-me-a-coffee&amp;logoColor=black&amp;style=for-the-badge" alt="Buy Me a Coffee" height="40"></a>
</p>
<!-- header:end -->

A starting point for a HACS integration with the shared pipeline already wired in: validation,
tests, HACS and manual ZIP packaging, GitHub releases and README badges.

## Using this template

1. Create a repository from this template, named `hass-<project>-integration`.
2. Rename `custom_components/example_integration/` and update the `domain` in `manifest.json`,
   `DOMAIN` in `const.py`, `filename` in `hacs.json` (`<domain>.zip`) and the repository URLs.
3. Replace the placeholder code and add real tests under `.github/tests/`. Add
   `requirements-dev.txt` to run them with pytest, or keep plain `unittest` files.
   `.github/ha_tests/` holds tests that run inside a real Home Assistant core; the Compatibility
   workflow runs them for every release from the `homeassistant` minimum in `hacs.json` upwards,
   so lower that minimum only as far as the tests pass.
4. Regenerate the header above (name, logo and badges) and commit the result:

   ```bash
   git clone https://github.com/seb5594/hass-workflows .engine   # private; needs access
   python .engine/.scripts/readme.py
   ```

5. Raise `version` in `manifest.json` and add a `CHANGELOG.md` entry for every release. A new
   version on `main` publishes the HACS ZIP, the manual ZIP and checksums; `a`, `b` and `rc`
   suffixes (for example `1.0.0b1`) become pre-releases.

The two workflows, `.github/workflows/ci.yml` and `compat.yml`, call the shared engine at a pinned
commit and need the `ORCHESTRATION_PAT` secret. Project-specific rules can go into `.github/checks/*.py`.

<!-- support:begin (generated, shared text) -->
## Say thanks

All my projects are built in my spare time, just for the fun of it. Still, they take a lot of time and care, and many of the smart home gadgets I buy end up here because I want to make them cloud-free and smart-home ready. Every bit of support means a lot to me.

If my work helped you or turned out to be useful, show your appreciation with a hot drink for my next sleepless night.

[![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/seb5594) [![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/seb5594)
<!-- support:end -->

<!-- license:begin (generated from the license file) -->
## License

[![license](https://img.shields.io/static/v1?label=license&message=Apache-2.0&color=5B6770&style=flat)](LICENSE)

Published under the [Apache License 2.0](LICENSE).
<!-- license:end -->
