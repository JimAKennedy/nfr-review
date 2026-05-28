#pragma once

#include <string>
#include <vector>

class AudioProcessor {
public:
    virtual void processBlock(float* buffer, int numSamples) = 0;
    virtual const char* getName() const = 0;
    virtual ~AudioProcessor() = default;

protected:
    int sampleRate_;
    int blockSize_;
};

class PluginProcessor : public AudioProcessor {
public:
    void processBlock(float* buffer, int numSamples) override;
    const char* getName() const override;
    void setParameter(int id, float value);

private:
    float gain_;
    std::vector<float> buffer_;
};

class EffectProcessor : public AudioProcessor {
public:
    void processBlock(float* buffer, int numSamples) override;
    const char* getName() const override;
    virtual void setMix(float wet);

protected:
    float mix_;
};

class ReverbProcessor : public EffectProcessor {
public:
    void processBlock(float* buffer, int numSamples) override;
    const char* getName() const override;
    void setMix(float wet) override;
    void setRoomSize(float size);

private:
    float roomSize_;
    float* delayLine_;
};

struct Config {
    int sampleRate;
    int blockSize;
    std::string name;
    void validate();
};
