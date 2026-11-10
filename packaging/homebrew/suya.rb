cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.6"
  sha256 arm:   "c8f2b5ce02ea31a9dce5c4e7604d39e09c73f7a15d3e60801bda3efe115ea626",
         intel: "41e48ed5a1a704c2d68565579a125f92628987204bab7c4cd99e78d6723ccd55"

  url "https://github.com/jongsu-king/SUYA/releases/download/v#{version}/SUYA-#{version}-macos-#{arch}.dmg"
  name "SUYA"
  desc "Collects Antarctic ocean temperature, salinity and air temperature"
  homepage "https://github.com/jongsu-king/SUYA"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: :monterey

  app "SUYA.app"

  zap trash: [
    "~/Library/Application Support/SUYA",
    "~/Library/Preferences/com.suya.monitor.plist",
    "~/Library/Saved Application State/com.suya.monitor.savedState",
  ]
end
