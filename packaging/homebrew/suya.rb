cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.4"
  sha256 arm:   "b24ffafd831e4204f75bb50a31062970de291abfc5e4660575a27915c2cfc7a2",
         intel: "603eb4c561287db764db692a36417c919a9ea365c31b2cc395481f27f87cafc6"

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
