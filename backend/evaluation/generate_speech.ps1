# Optional local fixture regeneration; Windows built-in speech, no API calls.
Add-Type -AssemblyName System.Speech
$fixtureDirectory = Join-Path $PSScriptRoot 'fixtures'
$fixtureSynth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $fixtureSynth.SetOutputToWaveFile((Join-Path $fixtureDirectory 'clear-question.wav'))
    $fixtureSynth.Speak('What are the main topics in this video?')
} finally {
    $fixtureSynth.Dispose()
}
Write-Output 'Created clear-question.wav locally. Run python evaluation/prepare_fixtures.py to regenerate deterministic noise and validation fixtures.'
