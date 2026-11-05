cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.2"
  sha256 arm:   "d3b581c07fca61cc1bf7d526647058680f8f852da69268a4978d25a4b79b5315",
         intel: "05f2ec459759b25b33aa7c44ac49361070ae25223544f5ac0abc37514fe827cc"

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
