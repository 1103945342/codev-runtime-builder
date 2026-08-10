# CodeV 独立运行时

该目录使用固定版本的 `robertkirkman/termux-generator` 补丁，在
`termux-packages` 源码阶段把运行路径改为：

```text
/data/data/com.codev/files/usr
```

生成过程不修改官方预编译 Bootstrap，也不对 ELF 做等长字节替换。

## 产物

```text
bootstrap-aarch64.zip
bootstrap-arm.zip
bootstrap-i686.zip
bootstrap-x86_64.zip
codev-bootstrap.properties
apt/
codev-apt-repository.tar.xz
runtime-build.txt
```

Bootstrap 由源码构建的 `tar.xz` 转换为当前 CodeV 安装器使用的旧式
ZIP 格式。符号链接统一记录在 `SYMLINKS.txt`。

APT 仓库中的包与 Bootstrap 使用同一个 `com.codev` 前缀，避免安装
开发依赖后重新写入 `/data/data/com.termux`。

构建阶段会额外应用 `patches/termux-packages/` 中的 CodeV 专用补丁。
补丁与构建脚本一同纳入版本控制，避免运行时依赖当前设备上已安装的
Termux 文件。

## Linux 或 GitHub Actions 构建

依赖：

```text
Docker
Git
patch
file
Python 3
dpkg-deb
```

执行：

```bash
bash tools/codev-runtime/build-codev-runtime.sh
```

仓库中的 `.github/workflows/build-codev-runtime.yml` 还会在
GitHub Actions 中完成以下流程：

1. 使用 Docker 从源码生成 Bootstrap 和 CodeV APT 仓库。
2. 将 `output/apt` 发布到 GitHub Pages。
3. 导入 Bootstrap 并构建 arm64 Release APK。
4. 上传运行时压缩包和 APK Artifact。

首次使用时，在仓库的 **Settings → Pages** 中将发布方式设为
**GitHub Actions**，之后手动运行该工作流即可。

只构建 ARM64：

```bash
bash tools/codev-runtime/build-codev-runtime.sh \
  --architectures aarch64
```

导入当前项目：

```bash
bash tools/codev-runtime/import-codev-runtime.sh \
  tools/codev-runtime/output
```

导入后，Gradle 的 `verifyCodevBootstraps` 会检查：

- 包名是否为 `com.codev`
- SHA-256 是否匹配
- ZIP 是否完整
- 是否包含 `SYMLINKS.txt`
- 是否残留 `/data/data/com.termux/files/usr`
- 是否真实包含 `/data/data/com.codev/files/usr`

## APT 发布

`output/apt` 是静态 Debian 仓库，可以发布到 GitHub Pages、Gitee
Pages、对象存储或普通 HTTPS 静态目录。

CodeV 构建时通过环境变量注入地址：

```bash
export CODEV_APT_REPOSITORY="https://HOST/PATH"
./gradlew :app:assembleRelease
```

若使用上述工作流，构建出来的 APK 会自动使用该仓库的 Pages 地址，
格式通常为：

```text
https://OWNER.github.io/REPOSITORY/
```

应用中的源格式为：

```text
deb [trusted=yes] https://HOST/PATH stable main
```
