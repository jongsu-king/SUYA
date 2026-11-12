cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.9"
  sha256 arm:   "7a3bc3c77e2ae2c58f2f8c7e114b47fd8d12557977bc932f520e8d2ba69f1d7d",
         intel: "2f19103abfd99b57735ae7a6e2180957383fa71accaea8c785c876da11d5cc38"

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
