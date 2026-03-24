# Repository File Listing

All files in the `RGoharimehr/extensionwebapp` repository, organized by directory.

---

## Root

```
.editorconfig
.gitattributes
.gitignore
.gitmodules
CHANGELOG.md
LICENSE
premake5.lua
PRODUCT_TERMS_OMNIVERSE
README.md
repo.bat
repo.sh
repo.toml
repo_tools.toml
SECURITY.md
```

---

## .github

```
.github/ISSUE_TEMPLATE/bug_report.yml
.github/ISSUE_TEMPLATE/feature_request.yml
.github/ISSUE_TEMPLATE/question.yml
.github/workflows/.github-ci.yml
.github/workflows/create_templates.py
.github/workflows/replay_files/base_editor
.github/workflows/replay_files/c_extension
.github/workflows/replay_files/c_python_extension
.github/workflows/replay_files/kit_service
.github/workflows/replay_files/python_extension
.github/workflows/replay_files/python_ui_extension
.github/workflows/replay_files/usd_composer
.github/workflows/replay_files/usd_explorer
.github/workflows/replay_files/usd_viewer
```

---

## .idea

```
.idea/.gitignore
.idea/PythonProject.iml
.idea/inspectionProfiles/profiles_settings.xml
.idea/misc.xml
.idea/modules.xml
.idea/vcs.xml
```

---

## .vscode

```
.vscode/launch.json
.vscode/replay_files/base_editor
.vscode/replay_files/usd_composer
.vscode/replay_files/usd_explorer
.vscode/replay_files/usd_viewer
.vscode/tasks.json
.vscode/template_builder.py
```

---

## readme-assets

```
readme-assets/additional-docs/data_collection_and_use.md
readme-assets/additional-docs/developer_bundle_extensions.md
readme-assets/additional-docs/dgxc_nvcf_deployment.md
readme-assets/additional-docs/kit_app_streaming_config.md
readme-assets/additional-docs/kit_app_template_tooling_guide.md
readme-assets/additional-docs/usage_and_troubleshooting.md
readme-assets/additional-docs/windows_developer_configuration.md
readme-assets/cpp_logo.png
readme-assets/cpp_python_bindings.png
readme-assets/kit_app_template_banner.png
readme-assets/kit_base_editor.png
readme-assets/kit_service.png
readme-assets/python-logo-only.png
readme-assets/python_ui_extension_template.jpg
readme-assets/streaming_base_editor.png
readme-assets/streaming_composer.png
readme-assets/streaming_explorer.png
readme-assets/streaming_viewer.png
readme-assets/usd_composer.jpg
readme-assets/usd_composer_default_launch.png
readme-assets/usd_explorer.jpg
readme-assets/usd_explorer_default_launch.png
readme-assets/usd_viewer.jpg
readme-assets/usd_viewer_default_launch.png
readme-assets/usd_viewer_load_asset_desktop.png
readme-assets/vs_additional.png
readme-assets/vs_download.png
readme-assets/vs_modify.png
readme-assets/vs_winsdk_verify.png
readme-assets/vs_workloads.png
```

---

## source

### source/apps

```
source/apps/my_company.my_editor.kit
source/rendered_template_metadata.json
```

### source/extensions/omnicool.webapp

```
source/extensions/omnicool.webapp/config/extension.toml
source/extensions/omnicool.webapp/data/icon.png
source/extensions/omnicool.webapp/data/preview.png
source/extensions/omnicool.webapp/data/webapp/asset-manifest.json
source/extensions/omnicool.webapp/data/webapp/index.html
source/extensions/omnicool.webapp/data/webapp/static/css/main.7785cb87.css
source/extensions/omnicool.webapp/data/webapp/static/css/main.7785cb87.css.map
source/extensions/omnicool.webapp/data/webapp/static/js/main.27268f8b.js
source/extensions/omnicool.webapp/data/webapp/static/js/main.27268f8b.js.LICENSE.txt
source/extensions/omnicool.webapp/data/webapp/static/js/main.27268f8b.js.map
source/extensions/omnicool.webapp/data/webapp/usd-editor.html
source/extensions/omnicool.webapp/docs/CHANGELOG.md
source/extensions/omnicool.webapp/docs/Overview.md
source/extensions/omnicool.webapp/docs/README.md
source/extensions/omnicool.webapp/docs/legacy/index.html.legacy
source/extensions/omnicool.webapp/docs/legacy/usd-editor.html.legacy
source/extensions/omnicool.webapp/frontend_source/README.md
source/extensions/omnicool.webapp/omnicool/webapp/__init__.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/__init__.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/bridge_ws_handlers.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/flownex_attr_tools.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/flownex_bridge.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/flownex_metadata.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/flownex_results.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/fnx_api.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/fnx_io_definition.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/fnx_units.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/usd_helpers.py
source/extensions/omnicool.webapp/omnicool/webapp/backend/ws_handlers.py
source/extensions/omnicool.webapp/omnicool/webapp/extension.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/__init__.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_flownex_bridge.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_flownex_metadata.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_flownex_results.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_hello_world.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_prim_hud.py
source/extensions/omnicool.webapp/omnicool/webapp/tests/test_webrtc_server.py
source/extensions/omnicool.webapp/omnicool/webapp/transport/__init__.py
source/extensions/omnicool.webapp/omnicool/webapp/transport/http_server.py
source/extensions/omnicool.webapp/omnicool/webapp/transport/webrtc_server.py
source/extensions/omnicool.webapp/premake5.lua
```

---

## templates

### templates/apps

```
templates/apps/kit_base_editor/README.md
templates/apps/kit_base_editor/kit_base_editor.kit
templates/apps/kit_service/README.md
templates/apps/kit_service/kit_service.kit
templates/apps/streaming_configs/README.md
templates/apps/streaming_configs/default_stream.kit
templates/apps/streaming_configs/gdn_stream.kit
templates/apps/streaming_configs/nvcf_stream.kit
templates/apps/streaming_configs/ovc_stream.kit
templates/apps/streaming_configs/ovc_stream_legacy.kit
templates/apps/usd_composer/README.md
templates/apps/usd_composer/omni.usd_composer.kit
templates/apps/usd_explorer/README.md
templates/apps/usd_explorer/omni.usd_explorer.kit
templates/apps/usd_viewer/README.md
templates/apps/usd_viewer/omni.usd_viewer.kit
```

### templates/extensions/basic_cpp

```
templates/extensions/basic_cpp/README.md
templates/extensions/basic_cpp/template/config/extension.toml
templates/extensions/basic_cpp/template/data/icon.png
templates/extensions/basic_cpp/template/data/preview.png
templates/extensions/basic_cpp/template/docs/CHANGELOG.md
templates/extensions/basic_cpp/template/docs/Overview.md
templates/extensions/basic_cpp/template/docs/README.md
templates/extensions/basic_cpp/template/plugins/{{extension_name}}/CppExtension.cpp
templates/extensions/basic_cpp/template/premake5.lua
templates/extensions/basic_cpp/template/tests.cpp/CppExampleTest.cpp
```

### templates/extensions/basic_python

```
templates/extensions/basic_python/README.md
templates/extensions/basic_python/template/config/extension.toml
templates/extensions/basic_python/template/data/icon.png
templates/extensions/basic_python/template/data/preview.png
templates/extensions/basic_python/template/docs/CHANGELOG.md
templates/extensions/basic_python/template/docs/Overview.md
templates/extensions/basic_python/template/docs/README.md
templates/extensions/basic_python/template/premake5.lua
templates/extensions/basic_python/template/{{python_module_path}}/__init__.py
templates/extensions/basic_python/template/{{python_module_path}}/extension.py
templates/extensions/basic_python/template/{{python_module_path}}/tests/__init__.py
templates/extensions/basic_python/template/{{python_module_path}}/tests/test_benchmarks.py
templates/extensions/basic_python/template/{{python_module_path}}/tests/test_hello.py
```

### templates/extensions/basic_python_binding

```
templates/extensions/basic_python_binding/README.md
templates/extensions/basic_python_binding/template/bindings/python/{{extension_name}}/ExamplePybindBindings.cpp
templates/extensions/basic_python_binding/template/bindings/python/{{extension_name}}/__init__.py
templates/extensions/basic_python_binding/template/config/extension.toml
templates/extensions/basic_python_binding/template/data/icon.png
templates/extensions/basic_python_binding/template/data/preview.png
templates/extensions/basic_python_binding/template/docs/CHANGELOG.md
templates/extensions/basic_python_binding/template/docs/Overview.md
templates/extensions/basic_python_binding/template/include/omni/example/cpp/pybind/{{interface_name}}.h
templates/extensions/basic_python_binding/template/include/omni/example/cpp/pybind/{{object_interface_name}}.h
templates/extensions/basic_python_binding/template/include/omni/example/cpp/pybind/{{object_name}}.h
templates/extensions/basic_python_binding/template/include/{{python_module_path}}/{{interface_name}}.h
templates/extensions/basic_python_binding/template/include/{{python_module_path}}/{{object_interface_name}}.h
templates/extensions/basic_python_binding/template/include/{{python_module_path}}/{{object_name}}.h
templates/extensions/basic_python_binding/template/plugins/{{extension_name}}.tests/ExamplePybindTests.cpp
templates/extensions/basic_python_binding/template/plugins/{{extension_name}}/ExamplePybindExtension.cpp
templates/extensions/basic_python_binding/template/premake5.lua
templates/extensions/basic_python_binding/template/python/impl/__init__.py
templates/extensions/basic_python_binding/template/python/impl/example_pybind_extension.py
templates/extensions/basic_python_binding/template/python/tests/__init__.py
templates/extensions/basic_python_binding/template/python/tests/test_pybind_example.py
```

### templates/extensions/python_ui

```
templates/extensions/python_ui/README.md
templates/extensions/python_ui/template/config/extension.toml
templates/extensions/python_ui/template/data/icon.png
templates/extensions/python_ui/template/data/preview.png
templates/extensions/python_ui/template/docs/CHANGELOG.md
templates/extensions/python_ui/template/docs/Overview.md
templates/extensions/python_ui/template/docs/README.md
templates/extensions/python_ui/template/premake5.lua
templates/extensions/python_ui/template/{{python_module_path}}/__init__.py
templates/extensions/python_ui/template/{{python_module_path}}/extension.py
templates/extensions/python_ui/template/{{python_module_path}}/tests/__init__.py
templates/extensions/python_ui/template/{{python_module_path}}/tests/test_hello_world.py
```

### templates/extensions/service.setup

```
templates/extensions/service.setup/README.md
templates/extensions/service.setup/template/config/extension.toml
templates/extensions/service.setup/template/data/icon.png
templates/extensions/service.setup/template/data/preview.png
templates/extensions/service.setup/template/docs/CHANGELOG.md
templates/extensions/service.setup/template/docs/Overview.md
templates/extensions/service.setup/template/docs/README.md
templates/extensions/service.setup/template/premake5.lua
templates/extensions/service.setup/template/{{python_module_path}}/__init__.py
templates/extensions/service.setup/template/{{python_module_path}}/extension.py
templates/extensions/service.setup/template/{{python_module_path}}/service.py
templates/extensions/service.setup/template/{{python_module_path}}/tests/__init__.py
templates/extensions/service.setup/template/{{python_module_path}}/tests/test_benchmarks.py
templates/extensions/service.setup/template/{{python_module_path}}/tests/test_service.py
```

### templates/extensions/usd_composer.setup

```
templates/extensions/usd_composer.setup/README.md
templates/extensions/usd_composer.setup/template/config/extension.toml
templates/extensions/usd_composer.setup/template/data/BuiltInMaterials.usda
templates/extensions/usd_composer.setup/template/data/flattener_materials/DrivesimPBR.mdl
templates/extensions/usd_composer.setup/template/data/flattener_materials/DrivesimPBR_Model.mdl
templates/extensions/usd_composer.setup/template/data/flattener_materials/DrivesimPBR_Opacity.mdl
templates/extensions/usd_composer.setup/template/data/flattener_materials/DrivesimPBR_Translucent.mdl
templates/extensions/usd_composer.setup/template/data/flattener_materials/OmniUe4Base.mdl
templates/extensions/usd_composer.setup/template/data/flattener_materials/OmniUe4Function.mdl
templates/extensions/usd_composer.setup/template/data/nvidia-omniverse-create.ico
templates/extensions/usd_composer.setup/template/data/nvidia-omniverse-create.png
templates/extensions/usd_composer.setup/template/data/nvidia-omniverse-usd_composer.ico
templates/extensions/usd_composer.setup/template/data/nvidia-omniverse-usd_composer.png
templates/extensions/usd_composer.setup/template/layouts/default.json
templates/extensions/usd_composer.setup/template/premake5.lua
templates/extensions/usd_composer.setup/template/{{python_module_path}}/__init__.py
templates/extensions/usd_composer.setup/template/{{python_module_path}}/extension.py
templates/extensions/usd_composer.setup/template/{{python_module_path}}/tests/__init__.py
templates/extensions/usd_composer.setup/template/{{python_module_path}}/tests/test_app_extensions.py
templates/extensions/usd_composer.setup/template/{{python_module_path}}/tests/test_app_startup.py
```

### templates/extensions/usd_explorer.setup

```
templates/extensions/usd_explorer.setup/README.md
templates/extensions/usd_explorer.setup/template/config/extension.toml
templates/extensions/usd_explorer.setup/template/data/BuiltInMaterials.usda
templates/extensions/usd_explorer.setup/template/data/icon.png
templates/extensions/usd_explorer.setup/template/data/icons/caret_s2_left_dark.svg
templates/extensions/usd_explorer.setup/template/data/icons/caret_s2_right_dark.svg
templates/extensions/usd_explorer.setup/template/data/icons/navOpen_dark.svg
templates/extensions/usd_explorer.setup/template/data/nvidia-omniverse-usd_explorer.ico
templates/extensions/usd_explorer.setup/template/data/nvidia-omniverse-usd_explorer.png
templates/extensions/usd_explorer.setup/template/data/nvidia-omniverse-usd_explorer_about.png
templates/extensions/usd_explorer.setup/template/data/preview.png
templates/extensions/usd_explorer.setup/template/docs/CHANGELOG.md
templates/extensions/usd_explorer.setup/template/docs/README.md
templates/extensions/usd_explorer.setup/template/layouts/comment_layout.json
templates/extensions/usd_explorer.setup/template/layouts/default.json
templates/extensions/usd_explorer.setup/template/layouts/markup_editor.json
templates/extensions/usd_explorer.setup/template/layouts/viewport_only.json
templates/extensions/usd_explorer.setup/template/premake5.lua
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/__init__.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/menu_helper.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/menubar_helper.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/navigation.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/setup.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/stage_template.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/tests/__init__.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/tests/test.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/tests/test_app_startup.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/tests/test_extensions.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/tests/test_state_manager.py
templates/extensions/usd_explorer.setup/template/{{python_module_path}}/ui_state_manager.py
```

### templates/extensions/usd_viewer.messaging

```
templates/extensions/usd_viewer.messaging/README.md
templates/extensions/usd_viewer.messaging/template/config/extension.toml
templates/extensions/usd_viewer.messaging/template/data/icon.png
templates/extensions/usd_viewer.messaging/template/data/preview.png
templates/extensions/usd_viewer.messaging/template/data/testing.usd
templates/extensions/usd_viewer.messaging/template/docs/CHANGELOG.md
templates/extensions/usd_viewer.messaging/template/docs/Overview.md
templates/extensions/usd_viewer.messaging/template/docs/README.md
templates/extensions/usd_viewer.messaging/template/premake5.lua
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/__init__.py
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/extension.py
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/stage_loading.py
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/stage_management.py
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/tests/__init__.py
templates/extensions/usd_viewer.messaging/template/{{python_module_path}}/tests/messaging_tests.py
```

### templates/extensions/usd_viewer.setup

```
templates/extensions/usd_viewer.setup/README.md
templates/extensions/usd_viewer.setup/template/config/extension.toml
templates/extensions/usd_viewer.setup/template/data/icon.png
templates/extensions/usd_viewer.setup/template/data/preview.png
templates/extensions/usd_viewer.setup/template/docs/CHANGELOG.md
templates/extensions/usd_viewer.setup/template/docs/Overview.md
templates/extensions/usd_viewer.setup/template/docs/README.md
templates/extensions/usd_viewer.setup/template/layouts/default.json
templates/extensions/usd_viewer.setup/template/premake5.lua
templates/extensions/usd_viewer.setup/template/{{python_module_path}}/__init__.py
templates/extensions/usd_viewer.setup/template/{{python_module_path}}/setup.py
templates/extensions/usd_viewer.setup/template/{{python_module_path}}/tests/__init__.py
templates/extensions/usd_viewer.setup/template/{{python_module_path}}/tests/test_app_extensions.py
templates/extensions/usd_viewer.setup/template/{{python_module_path}}/tests/test_app_startup.py
```

### templates (root)

```
templates/templates.toml
```

---

## tools

```
tools/VERSION.md
tools/deps/host-deps.packman.xml
tools/deps/kit-sdk-deps.packman.xml
tools/deps/kit-sdk.packman.xml
tools/deps/pip.toml
tools/deps/repo-deps.packman.xml
tools/deps/user.toml
tools/package.bat
tools/package.sh
tools/packman/bootstrap/configure.bat
tools/packman/bootstrap/download_file_from_url.ps1
tools/packman/bootstrap/fetch_file_from_packman_bootstrap.cmd
tools/packman/bootstrap/generate_temp_file_name.ps1
tools/packman/bootstrap/generate_temp_folder.ps1
tools/packman/bootstrap/install_package.py
tools/packman/config.packman.xml
tools/packman/packman
tools/packman/packman.cmd
tools/packman/packmanconf.py
tools/packman/python.bat
tools/packman/python.sh
tools/repoman/launch.py
tools/repoman/package.py
tools/repoman/repoman.py
tools/repoman/repoman_bootstrapper.py
```

---

*Total: 305 files (excluding `.git` internals)*
