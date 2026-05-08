using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace SampleApp
{
    public class GoodCode
    {
        private readonly ILogger<GoodCode> _logger;

        public GoodCode(ILogger<GoodCode> logger)
        {
            _logger = logger;
        }

        public async Task<string> ReadFileAsync(string path)
        {
            using var fs = new FileStream(path, FileMode.Open);
            using var reader = new StreamReader(fs);
            var content = await reader.ReadToEndAsync().ConfigureAwait(false);
            return content;
        }

        public void HandleError()
        {
            try
            {
                DoWork();
            }
            catch (InvalidOperationException ex)
            {
                _logger.LogError(ex, "Operation failed");
                throw;
            }
        }

        public async Task ProcessAsync()
        {
            await Task.Delay(100).ConfigureAwait(false);
            _logger.LogInformation("Processing complete");
        }

        private void DoWork() { }
    }
}
