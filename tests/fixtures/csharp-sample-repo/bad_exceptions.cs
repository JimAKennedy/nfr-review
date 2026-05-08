using System;
using System.IO;

namespace SampleApp
{
    public class BadExceptions
    {
        public void BareCatch()
        {
            try
            {
                File.ReadAllText("data.txt");
            }
            catch
            {
                // swallowed
            }
        }

        public void CatchException()
        {
            try
            {
                int.Parse("abc");
            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.Message);
            }
        }

        public void CatchWithoutRethrow()
        {
            try
            {
                DoWork();
            }
            catch (InvalidOperationException ex)
            {
                Log(ex.Message);
            }
        }

        public void CatchWithRethrow()
        {
            try
            {
                DoWork();
            }
            catch (IOException ex)
            {
                Log(ex.Message);
                throw;
            }
        }

        private void DoWork() { }
        private void Log(string msg) { }
    }
}
