using System;
using System.Data.SqlClient;
using System.IO;
using System.Net.Http;

namespace SampleApp
{
    public class BadDisposable
    {
        public void LeakedFileStream()
        {
            var fs = new FileStream("data.bin", FileMode.Open);
            fs.Read(new byte[100], 0, 100);
        }

        public void LeakedSqlConnection()
        {
            var conn = new SqlConnection("Server=.;Database=test");
            conn.Open();
        }

        public void LeakedHttpClient()
        {
            var client = new HttpClient();
            client.GetAsync("http://example.com");
        }

        public void ProperUsing()
        {
            using (var fs = new FileStream("data.bin", FileMode.Open))
            {
                fs.Read(new byte[100], 0, 100);
            }
        }

        public void ProperUsingDeclaration()
        {
            using var fs = new FileStream("data.bin", FileMode.Open);
            fs.Read(new byte[100], 0, 100);
        }
    }
}
