# Build the Onyx iOS 26 kernel on GitHub Actions

The manual workflow is `.github/workflows/build-onyx-ios26.yml`. It uses the
standard `macos-26` runner and selects Xcode 26.6 by default. The installed Xcode
version is an input: if the requested version is unavailable, the job lists
installed Xcode applications and fails instead of silently using another compiler.

The workflow is prepared for [arbuxiktech/hakios-arm64e-onyx](https://github.com/arbuxiktech/hakios-arm64e-onyx).
Local syntax and helper checks do not establish that a remote build succeeds;
use the actual Actions run and its artifacts to assess build status.

## What the job does

1. Fetches the pinned Dada and Onyx reference sources and Apple XNU 12377 source.
2. Applies the Onyx passive-touch overlay and prepares a private build environment.
3. Uses Apple's clang, iPhoneOS SDK and real IIG from the selected Xcode.
   The macOS IIG wrapper fails if the generator is absent or rejects the source;
   it cannot substitute an empty generated interface.
4. Builds support libraries and the kernel. Errors stop the build; an unstripped
   intermediate file is not substituted for a failed final link.
5. Checks the resulting Mach-O architecture, CPU subtype and executable type.
   Requires the Onyx diagnostic string to survive in the linked kernel.
6. Uploads the kernel, SHA-256 and build records. Logs are uploaded even when the
   build fails, allowing the next source compatibility issue to be diagnosed.

The kernel artifact does not establish a successful hardware boot. Touch remains
passive diagnostics, and the output is not an Android boot image.

No IPSW, stock ROM, userdata, phone access or device firmware is needed for this
kernel compilation job. Nothing is flashed or repartitioned. The workflow has
read-only repository permissions and runs only when manually dispatched.

## Run it from the repository

Open the repository's **Actions** tab, choose **Build Onyx iOS 26 kernel**, and
select **Run workflow**. Use an Xcode version installed on the selected runner.
The resulting artifact is named `onyx-ios26-kernel-<run number>` and is retained
for 14 days. A failed job's artifact contains diagnostic logs, not a working kernel.

This is a build path to address the Linux IIG/compiler limitations. The first
macOS build may expose additional compatibility errors; those must be resolved
from its real logs before any boot-image packaging.

References:

- [GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [macOS 26 installed software](https://github.com/actions/runner-images/blob/main/images/macos/macos-26-arm64-Readme.md)
- [Onyx reference kernel workflow](https://github.com/Aymon-njz/hackios-xnu-kernel-Onyx/blob/main/.github/workflows/onyx-kernel.yml)
