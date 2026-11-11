cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.8"
  sha256 arm:   "ca21c17152a67db9fc0c3bda7780e2ec4bfd8bc2d764f19837027761db0ebe2d",
         intel: "bd3b4d710d936be36c23cbd15fbd0e26fab4ea242ff422c36b99515b1def4285"

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
