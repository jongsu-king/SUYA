cask "suya" do
  arch arm: "arm64", intel: "x86_64"

  version "0.1.7"
  sha256 arm:   "2b93fb9a87496c032a543e831e911662f1be0293317830a5d1fef9ebbed9c370",
         intel: "b130b8e930f1864f6798f8bb2a6044a274e17774cd15cdb8a82e08a37ce03ff1"

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
